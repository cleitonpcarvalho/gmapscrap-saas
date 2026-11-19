-- Additive migration. Does not read or modify leads or historical searches.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '45s';

CREATE TABLE IF NOT EXISTS public.niches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_niches_name CHECK (
        length(trim(name)) BETWEEN 2 AND 255 AND name = trim(name)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_niches_lower_name ON public.niches (lower(name));

-- GmapScrap uses its own signed session, not Supabase Auth.
-- Only the trusted backend database owner/BYPASSRLS role may access this table.
ALTER TABLE public.niches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.niches FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.niches_id_seq FROM PUBLIC;
DO $$
DECLARE api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.niches FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON SEQUENCE public.niches_id_seq FROM %I', api_role);
        END IF;
    END LOOP;
END $$;
COMMIT;
