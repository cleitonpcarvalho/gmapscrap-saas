-- Explicit local/reviewed migration. No backfill or changes to existing rows.
-- Apply later as the existing effective postgres owner, after manual CRM phase 1.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('gmapscrap_crm_company_profiles_20261124'));

DO $owner$
BEGIN
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'Company profiles require the existing effective postgres owner';
    END IF;
END
$owner$;

CREATE TABLE IF NOT EXISTS public.crm_company_profiles (
    lead_id integer PRIMARY KEY REFERENCES public.leads(id) ON DELETE CASCADE,
    niche_override varchar(255),
    location_override varchar(255),
    contact_name varchar(255),
    contact_phone varchar(80),
    contact_email varchar(255),
    version integer NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_crm_company_profile_version CHECK (version >= 1)
);

DO $security$
DECLARE
    api_role text;
    role_sql text;
    columns_sql text;
    target oid := 'public.crm_company_profiles'::regclass;
BEGIN
    IF NOT EXISTS (SELECT FROM pg_class WHERE oid=target AND relkind='r'
        AND NOT relispartition AND relowner=(SELECT oid FROM pg_roles WHERE rolname='postgres'))
        OR EXISTS (SELECT FROM pg_policy WHERE polrelid=target)
        OR EXISTS (SELECT FROM pg_inherits WHERE inhparent=target OR inhrelid=target) THEN
        RAISE EXCEPTION 'Review company profile ownership, policies or inheritance before migrating';
    END IF;
    ALTER TABLE public.crm_company_profiles ENABLE ROW LEVEL SECURITY;
    GRANT ALL ON TABLE public.crm_company_profiles TO postgres;
    SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO columns_sql
        FROM pg_attribute WHERE attrelid=target AND attnum>0 AND NOT attisdropped;
    FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
        IF api_role <> 'PUBLIC' AND NOT EXISTS(SELECT FROM pg_roles WHERE rolname=api_role) THEN CONTINUE; END IF;
        role_sql := CASE WHEN api_role='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
        EXECUTE format('REVOKE ALL ON TABLE public.crm_company_profiles FROM %s RESTRICT', role_sql);
        EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE public.crm_company_profiles FROM %s RESTRICT', columns_sql, role_sql);
    END LOOP;
    FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
        IF has_table_privilege(api_role,target,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            OR has_any_column_privilege(api_role,target,'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Company profile privileges remain for %; review inherited grants', api_role;
        END IF;
    END LOOP;
END
$security$;
COMMIT;
