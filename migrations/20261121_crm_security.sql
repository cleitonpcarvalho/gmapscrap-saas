-- Security only: existing CRM tables, their owned sequences and related routines.
-- Apply explicitly as the existing effective postgres owner, before manual CRM.
-- No row changes, schema backfills, ownership changes, policy removal or CASCADE.
-- No global/default privilege changes. Recheck new routines after later migrations.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('gmapscrap_crm_security_20261121'));

DO $security$
DECLARE
    table_name text;
    target_oid oid;
    target_oids oid[] := ARRAY[]::oid[];
    sequence_oids oid[] := ARRAY[]::oid[];
    routine_oids oid[] := ARRAY[]::oid[];
    backend_oid oid;
    api_role text;
    role_sql text;
    columns_sql text;
    object record;
    exposed_view text;
    unclassified_definer text;
BEGIN
    SELECT oid INTO backend_oid FROM pg_roles WHERE rolname = 'postgres';
    IF backend_oid IS NULL OR current_user <> 'postgres' THEN
        RAISE EXCEPTION 'CRM security requires the existing effective postgres owner';
    END IF;

    FOREACH table_name IN ARRAY ARRAY['crm_funnels','crm_funnel_stages','crm_leads','crm_stage_history'] LOOP
        target_oid := to_regclass(format('public.%I', table_name));
        IF target_oid IS NULL OR NOT EXISTS (
            SELECT FROM pg_class WHERE oid = target_oid AND relkind = 'r'
                AND NOT relispartition AND relowner = backend_oid
        ) THEN
            RAISE EXCEPTION 'Expected ordinary postgres-owned table public.%', table_name;
        END IF;
        target_oids := array_append(target_oids, target_oid);
        IF pg_get_serial_sequence(format('public.%I', table_name), 'id') IS NULL THEN
            RAISE EXCEPTION 'Expected an owned id sequence for public.%', table_name;
        END IF;
    END LOOP;
    IF EXISTS (SELECT FROM pg_inherits WHERE inhparent = ANY(target_oids) OR inhrelid = ANY(target_oids)) THEN
        RAISE EXCEPTION 'Review CRM inheritance/partitions before applying security';
    END IF;
    IF EXISTS (SELECT FROM pg_policy WHERE polrelid = ANY(target_oids)) THEN
        RAISE EXCEPTION 'Review existing CRM RLS policies before applying security';
    END IF;

    -- Fail rather than silently leave an owner-executed view bypass in place.
    WITH RECURSIVE dependents(oid) AS (
        SELECT unnest(target_oids)
        UNION
        SELECT rewrite.ev_class
        FROM dependents parent
        JOIN pg_depend dependency ON dependency.refclassid = 'pg_class'::regclass
            AND dependency.refobjid = parent.oid AND dependency.classid = 'pg_rewrite'::regclass
        JOIN pg_rewrite rewrite ON rewrite.oid = dependency.objid
    )
    SELECT format('%I.%I', namespace.nspname, relation.relname) INTO exposed_view
    FROM dependents
    JOIN pg_class relation USING (oid)
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE relation.relkind IN ('v','m') AND EXISTS (
        SELECT FROM pg_roles api WHERE api.rolname IN ('anon','authenticated')
            AND has_any_column_privilege(api.oid, relation.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
    ) LIMIT 1;
    IF exposed_view IS NOT NULL THEN
        RAISE EXCEPTION 'Review exposed dependent view % before applying CRM security', exposed_view;
    END IF;

    LOCK TABLE public.crm_funnels, public.crm_funnel_stages,
        public.crm_leads, public.crm_stage_history IN ACCESS EXCLUSIVE MODE;

    SELECT coalesce(array_agg(sequence.oid ORDER BY sequence.oid), ARRAY[]::oid[])
    INTO sequence_oids
    FROM pg_class sequence
    JOIN pg_depend ownership ON ownership.classid = 'pg_class'::regclass
        AND ownership.objid = sequence.oid AND ownership.refclassid = 'pg_class'::regclass
        AND ownership.refobjid = ANY(target_oids) AND ownership.deptype IN ('a','i')
    WHERE sequence.relkind = 'S';
    IF EXISTS (SELECT FROM pg_class WHERE oid = ANY(sequence_oids) AND relowner <> backend_oid) THEN
        RAISE EXCEPTION 'Expected postgres-owned CRM sequences';
    END IF;

    -- SQL-standard bodies have catalog dependencies; PL/pgSQL bodies often do
    -- not. Include explicit CRM source references and attached trigger routines.
    -- Do not rewrite routine bodies, SECURITY DEFINER flags or search paths.
    WITH RECURSIVE related(oid) AS (
        SELECT routine.oid FROM pg_proc routine
        JOIN pg_namespace namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public' AND routine.prokind IN ('f','p') AND (
            EXISTS (SELECT FROM pg_trigger WHERE tgrelid = ANY(target_oids)
                AND tgfoid = routine.oid AND NOT tgisinternal)
            OR EXISTS (
                SELECT FROM pg_depend dependency WHERE dependency.classid = 'pg_proc'::regclass
                    AND dependency.objid = routine.oid AND (
                        dependency.refclassid = 'pg_class'::regclass
                            AND dependency.refobjid = ANY(target_oids || sequence_oids)
                        OR dependency.refclassid = 'pg_type'::regclass
                            AND dependency.refobjid IN (SELECT reltype FROM pg_class WHERE oid = ANY(target_oids))
                    )
            )
            OR routine.prosrc ~ '\mcrm_(leads|funnels|funnel_stages|stage_history)(_id_seq)?\M'
            OR routine.oid = to_regprocedure('public.gmapscrap_crm_activity_immutable()')
        )
        UNION
        SELECT dependency.objid FROM related parent
        JOIN pg_depend dependency ON dependency.refclassid = 'pg_proc'::regclass
            AND dependency.refobjid = parent.oid AND dependency.classid = 'pg_proc'::regclass
    )
    SELECT coalesce(array_agg(DISTINCT oid), ARRAY[]::oid[]) INTO routine_oids FROM related;

    -- An untracked definer RPC can bypass table RLS. Do not guess its purpose or
    -- silently revoke unrelated RPCs; require review and leave everything intact.
    SELECT routine.oid::regprocedure::text INTO unclassified_definer
    FROM pg_proc routine JOIN pg_namespace namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname = 'public' AND routine.prosecdef AND routine.prokind IN ('f','p')
        AND NOT routine.oid = ANY(routine_oids) AND EXISTS (
            SELECT FROM pg_roles api WHERE api.rolname IN ('anon','authenticated')
                AND has_function_privilege(api.oid, routine.oid, 'EXECUTE')
        ) LIMIT 1;
    IF unclassified_definer IS NOT NULL THEN
        RAISE EXCEPTION 'Review unclassified browser-executable SECURITY DEFINER routine % before CRM security', unclassified_definer;
    END IF;

    FOREACH target_oid IN ARRAY target_oids LOOP
        SELECT string_agg(format('%I', attname), ', ' ORDER BY attnum) INTO columns_sql
        FROM pg_attribute WHERE attrelid = target_oid AND attnum > 0 AND NOT attisdropped;
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', target_oid::regclass);
        EXECUTE format('GRANT ALL PRIVILEGES ON TABLE %s TO postgres', target_oid::regclass);
        FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
            IF api_role <> 'PUBLIC' AND NOT EXISTS (SELECT FROM pg_roles WHERE rolname = api_role) THEN
                CONTINUE;
            END IF;
            role_sql := CASE WHEN api_role = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %s FROM %s RESTRICT', target_oid::regclass, role_sql);
            -- Table REVOKE does not remove independent column ACLs.
            EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE %s FROM %s RESTRICT', columns_sql, target_oid::regclass, role_sql);
        END LOOP;
    END LOOP;

    FOREACH target_oid IN ARRAY sequence_oids LOOP
        EXECUTE format('GRANT ALL PRIVILEGES ON SEQUENCE %s TO postgres', target_oid::regclass);
        FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
            IF api_role <> 'PUBLIC' AND NOT EXISTS (SELECT FROM pg_roles WHERE rolname = api_role) THEN CONTINUE; END IF;
            role_sql := CASE WHEN api_role = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
            EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM %s RESTRICT', target_oid::regclass, role_sql);
        END LOOP;
    END LOOP;

    FOR object IN
        SELECT oid, oid::regprocedure AS signature FROM pg_proc WHERE oid = ANY(routine_oids)
    LOOP
        IF EXISTS (SELECT FROM pg_depend WHERE classid = 'pg_proc'::regclass
            AND objid = object.oid AND deptype = 'e') THEN
            RAISE EXCEPTION 'Review extension-owned CRM routine % separately', object.signature;
        END IF;
        EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO postgres', object.signature);
        FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
            IF api_role <> 'PUBLIC' AND NOT EXISTS (SELECT FROM pg_roles WHERE rolname = api_role) THEN CONTINUE; END IF;
            role_sql := CASE WHEN api_role = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
            EXECUTE format('REVOKE ALL PRIVILEGES ON ROUTINE %s FROM %s RESTRICT', object.signature, role_sql);
        END LOOP;
    END LOOP;

    -- Check effective privileges, including inherited grants, before COMMIT.
    -- Unexpected role memberships abort everything instead of changing roles.
    FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
        FOREACH target_oid IN ARRAY target_oids LOOP
            IF has_table_privilege(api_role, target_oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                OR has_any_column_privilege(api_role, target_oid, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'CRM privileges remain for % on %; review inherited grants', api_role, target_oid::regclass;
            END IF;
        END LOOP;
        FOREACH target_oid IN ARRAY sequence_oids LOOP
            IF has_sequence_privilege(api_role, target_oid, 'USAGE,SELECT,UPDATE') THEN
                RAISE EXCEPTION 'CRM sequence privileges remain for %; review inherited grants', api_role;
            END IF;
        END LOOP;
        FOREACH target_oid IN ARRAY routine_oids LOOP
            IF has_function_privilege(api_role, target_oid, 'EXECUTE') THEN
                RAISE EXCEPTION 'CRM routine privileges remain for %; review inherited grants', api_role;
            END IF;
        END LOOP;
    END LOOP;
END
$security$;
COMMIT;
