-- Explicit security migration for the existing effective postgres owner (PG17+).
-- No business-row changes, backfills, ownership/role changes, CASCADE or policies.
-- Also closes API defaults for FUTURE postgres-created public tables/sequences.
-- Provider-owned supabase_admin defaults are reviewed/reported, never modified.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL search_path = pg_catalog;

DO $security$
DECLARE
    backend_oid oid;
    public_oid oid := 'public'::regnamespace;
    table_name text;
    target oid;
    targets oid[] := ARRAY[]::oid[];
    sequences oid[] := ARRAY[]::oid[];
    serial_sequence text;
    api_role text;
    role_sql text;
    columns_sql text;
    privilege_name text;
    exposed_view text;
    exposed_definer text;
    object record;
BEGIN
    SELECT oid INTO backend_oid FROM pg_roles WHERE rolname = 'postgres';
    IF backend_oid IS NULL OR current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Lead security requires the existing effective postgres owner';
    END IF;
    IF current_setting('server_version_num')::integer < 170000 THEN
        RAISE EXCEPTION 'Lead security requires PostgreSQL 17 or newer';
    END IF;
    IF NOT pg_try_advisory_xact_lock(hashtext('gmapscrap_lead_security_20261124')) THEN
        RAISE EXCEPTION 'Lead security is already running; retry after it finishes';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role' AND rolbypassrls) THEN
        RAISE EXCEPTION 'Review the expected service_role BYPASSRLS configuration';
    END IF;
    FOREACH api_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = api_role
            AND NOT rolsuper AND NOT rolbypassrls)
            OR pg_has_role(api_role, backend_oid, 'SET')
            OR pg_has_role(api_role, 'service_role', 'SET')
            OR has_schema_privilege(api_role, public_oid, 'CREATE') THEN
            RAISE EXCEPTION 'Review unsafe or missing API role % before lead security', api_role;
        END IF;
    END LOOP;

    FOREACH table_name IN ARRAY ARRAY['leads','search_runs','lead_tags','tags'] LOOP
        target := to_regclass(format('public.%I', table_name));
        IF target IS NULL OR NOT EXISTS (SELECT FROM pg_class WHERE oid = target
            AND relkind = 'r' AND NOT relispartition AND relowner = backend_oid
            AND NOT relforcerowsecurity) THEN
            RAISE EXCEPTION 'Expected ordinary postgres-owned table public.% without FORCE RLS', table_name;
        END IF;
        targets := array_append(targets, target);
    END LOOP;
    -- Do not queue behind scraping/CRM transactions while holding partial locks.
    LOCK TABLE public.search_runs, public.leads, public.tags, public.lead_tags
        IN ACCESS EXCLUSIVE MODE NOWAIT;
    IF EXISTS (SELECT FROM pg_inherits WHERE inhparent = ANY(targets) OR inhrelid = ANY(targets))
        OR EXISTS (SELECT FROM pg_policy WHERE polrelid = ANY(targets)) THEN
        RAISE EXCEPTION 'Review existing lead RLS policies or inheritance before migrating';
    END IF;

    SELECT coalesce(array_agg(sequence.oid ORDER BY sequence.oid), ARRAY[]::oid[])
    INTO sequences FROM pg_class sequence
    JOIN pg_depend ownership ON ownership.classid = 'pg_class'::regclass
        AND ownership.objid = sequence.oid AND ownership.refclassid = 'pg_class'::regclass
        AND ownership.refobjid = ANY(targets) AND ownership.deptype IN ('a','i')
    WHERE sequence.relkind = 'S';
    IF EXISTS (SELECT FROM pg_class WHERE oid = ANY(sequences)
        AND (relowner <> backend_oid OR relnamespace <> public_oid)) THEN
        RAISE EXCEPTION 'Review unexpected lead sequence ownership/schema';
    END IF;
    FOREACH table_name IN ARRAY ARRAY['leads','search_runs','tags'] LOOP
        serial_sequence := pg_get_serial_sequence(format('public.%I', table_name), 'id');
        IF serial_sequence IS NULL OR NOT to_regclass(serial_sequence) = ANY(sequences) THEN
            RAISE EXCEPTION 'Expected an owned id sequence for public.%', table_name;
        END IF;
    END LOOP;

    -- A definer view or RPC could bypass RLS. Abort for review instead of silently
    -- rewriting views/functions or removing privileges from unrelated objects.
    WITH RECURSIVE dependents(oid) AS (
        SELECT unnest(targets)
        UNION
        SELECT rewrite.ev_class FROM dependents parent
        JOIN pg_depend dependency ON dependency.refclassid = 'pg_class'::regclass
            AND dependency.refobjid = parent.oid AND dependency.classid = 'pg_rewrite'::regclass
        JOIN pg_rewrite rewrite ON rewrite.oid = dependency.objid
    )
    SELECT format('%I.%I', namespace.nspname, relation.relname) INTO exposed_view
    FROM dependents JOIN pg_class relation USING (oid)
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE relation.relkind IN ('v','m') AND EXISTS (
        SELECT FROM pg_roles api WHERE api.rolname IN ('anon','authenticated') AND (
            has_table_privilege(api.oid, relation.oid, 'SELECT,INSERT,UPDATE,DELETE')
            OR has_any_column_privilege(api.oid, relation.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
        )
    ) LIMIT 1;
    IF exposed_view IS NOT NULL THEN
        RAISE EXCEPTION 'Review exposed dependent view % before lead security', exposed_view;
    END IF;
    SELECT routine.oid::regprocedure::text INTO exposed_definer
    FROM pg_proc routine JOIN pg_namespace namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname = 'public' AND routine.prokind IN ('f','p') AND routine.prosecdef
        AND EXISTS (SELECT FROM pg_roles api WHERE api.rolname IN ('anon','authenticated')
            AND has_function_privilege(api.oid, routine.oid, 'EXECUTE')) LIMIT 1;
    IF exposed_definer IS NOT NULL THEN
        RAISE EXCEPTION 'Review browser-executable SECURITY DEFINER routine % before lead security', exposed_definer;
    END IF;

    -- Schema-local REVOKE cannot override global default grants. Do not silently
    -- change defaults in other schemas; abort if a global grant defeats this fix.
    IF EXISTS (
        SELECT FROM pg_default_acl defaults
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) acl
        WHERE defaults.defaclrole = backend_oid AND defaults.defaclnamespace = 0
            AND defaults.defaclobjtype IN ('r','S') AND (
                acl.grantee = 0 OR EXISTS (SELECT FROM pg_roles api
                    WHERE api.rolname IN ('anon','authenticated')
                        AND pg_has_role(api.oid, acl.grantee, 'USAGE'))
            )
    ) THEN
        RAISE EXCEPTION 'Review global postgres table/sequence default grants before lead security';
    END IF;

    FOREACH target IN ARRAY targets LOOP
        SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO columns_sql
        FROM pg_attribute WHERE attrelid = target AND attnum > 0 AND NOT attisdropped;
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', target::regclass);
        FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
            role_sql := CASE WHEN api_role = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %s FROM %s RESTRICT', target::regclass, role_sql);
            EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE %s FROM %s RESTRICT', columns_sql, target::regclass, role_sql);
        END LOOP;
    END LOOP;
    FOREACH target IN ARRAY sequences LOOP
        EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM PUBLIC, anon, authenticated RESTRICT', target::regclass);
    END LOOP;
    ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated RESTRICT;
    ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated RESTRICT;

    -- Check EFFECTIVE access, not only direct ACLs. Unexpected inheritance rolls
    -- the entire transaction back, including RLS and default-privilege changes.
    FOREACH api_role IN ARRAY ARRAY['anon','authenticated'] LOOP
        FOREACH target IN ARRAY targets LOOP
            IF has_table_privilege(api_role, target, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                OR has_any_column_privilege(api_role, target, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'Lead privileges remain for % on %; review inherited grants', api_role, target::regclass;
            END IF;
        END LOOP;
        FOREACH target IN ARRAY sequences LOOP
            IF has_sequence_privilege(api_role, target, 'USAGE,SELECT,UPDATE') THEN
                RAISE EXCEPTION 'Lead sequence privileges remain for %; review inherited grants', api_role;
            END IF;
        END LOOP;
    END LOOP;
    IF EXISTS (
        SELECT FROM pg_default_acl defaults
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) acl
        WHERE defaults.defaclrole = backend_oid AND defaults.defaclnamespace IN (0,public_oid)
            AND defaults.defaclobjtype IN ('r','S') AND (
                acl.grantee = 0 OR EXISTS (SELECT FROM pg_roles api
                    WHERE api.rolname IN ('anon','authenticated')
                        AND pg_has_role(api.oid, acl.grantee, 'USAGE'))
            )
    ) THEN
        RAISE EXCEPTION 'API privileges remain in postgres defaults; review inherited grants';
    END IF;
    FOREACH api_role IN ARRAY ARRAY['postgres','service_role'] LOOP
        FOREACH target IN ARRAY targets LOOP
            FOREACH privilege_name IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN'] LOOP
                IF NOT has_table_privilege(api_role, target, privilege_name) THEN
                    RAISE EXCEPTION 'Expected backend % privilege % on %', api_role, privilege_name, target::regclass;
                END IF;
            END LOOP;
        END LOOP;
        FOREACH target IN ARRAY sequences LOOP
            FOREACH privilege_name IN ARRAY ARRAY['USAGE','SELECT','UPDATE'] LOOP
                IF NOT has_sequence_privilege(api_role, target, privilege_name) THEN
                    RAISE EXCEPTION 'Expected backend sequence privilege % for % on %', privilege_name, api_role, target::regclass;
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;

    FOR object IN
        SELECT DISTINCT pg_get_userbyid(defaults.defaclrole) AS owner
        FROM pg_default_acl defaults
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) acl
        WHERE defaults.defaclrole <> backend_oid AND defaults.defaclnamespace IN (0,public_oid)
            AND defaults.defaclobjtype IN ('r','S') AND (
                acl.grantee = 0 OR EXISTS (SELECT FROM pg_roles api
                    WHERE api.rolname IN ('anon','authenticated')
                        AND pg_has_role(api.oid, acl.grantee, 'USAGE'))
            )
    LOOP
        RAISE NOTICE 'Unchanged provider/other creator defaults for %: secure new objects created by that role separately', object.owner;
    END LOOP;
END
$security$;
COMMIT;
