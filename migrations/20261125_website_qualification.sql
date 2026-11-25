-- Additive derived observations and durable work only. Never updates Lead/SearchRun/CRM.
-- Requires the existing effective postgres owner. Installed by the backup/restore gate.
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='60s';
SET LOCAL search_path=pg_catalog;
SELECT pg_advisory_xact_lock(hashtext('gmapscrap_website_qualification_20261125'));
DO $owner$ BEGIN
 IF current_user <> 'postgres' THEN RAISE EXCEPTION 'Website qualification requires existing postgres owner'; END IF;
END $owner$;

CREATE TABLE IF NOT EXISTS public.lead_website_qualifications (
	lead_id INTEGER NOT NULL,
	normalized_website VARCHAR(2048),
	website_sha256 VARCHAR(64) NOT NULL,
	site_availability VARCHAR(30) NOT NULL,
	cms VARCHAR(30) NOT NULL,
	cms_name VARCHAR(80),
	wordpress_status VARCHAR(30) NOT NULL,
	blog_status VARCHAR(30) NOT NULL,
	blog_url VARCHAR(2048),
	total_posts INTEGER,
	last_published_at TIMESTAMP WITH TIME ZONE,
	last_post_title VARCHAR(500),
	last_post_url VARCHAR(2048),
	days_since_publication INTEGER,
	priority VARCHAR(20) NOT NULL,
	validation_status VARCHAR(30) NOT NULL,
	checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
	evidence JSON NOT NULL,
	errors JSON NOT NULL,
	PRIMARY KEY (lead_id),
	CONSTRAINT ck_website_cms CHECK (cms IN ('WordPress','other','unknown')),
	CONSTRAINT ck_website_priority CHECK (priority IN ('HIGH','MEDIUM','LOW','INCONCLUSIVE')),
	CONSTRAINT ck_website_total CHECK (total_posts IS NULL OR total_posts >= 0),
	CONSTRAINT ck_website_days CHECK (days_since_publication IS NULL OR days_since_publication >= 0),
	FOREIGN KEY(lead_id) REFERENCES public.leads (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_lead_website_qualifications_priority ON public.lead_website_qualifications (priority);

CREATE TABLE IF NOT EXISTS public.website_qualification_jobs (
	id VARCHAR(36) NOT NULL,
	status VARCHAR(20) NOT NULL,
	total INTEGER NOT NULL,
	processed INTEGER NOT NULL,
	failed INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_website_job_status CHECK (status IN ('queued','running','completed'))
);

CREATE TABLE IF NOT EXISTS public.website_qualification_items (
	job_id VARCHAR(36) NOT NULL,
	lead_id INTEGER NOT NULL,
	active_lead_id INTEGER,
	source_website VARCHAR(500),
	status VARCHAR(20) NOT NULL,
	error VARCHAR(80),
	PRIMARY KEY (job_id, lead_id),
	CONSTRAINT ck_website_item_status CHECK (status IN ('queued','running','completed','failed')),
	CONSTRAINT ck_website_item_active CHECK (active_lead_id IS NULL OR active_lead_id = lead_id),
	FOREIGN KEY(job_id) REFERENCES public.website_qualification_jobs (id) ON DELETE CASCADE,
	FOREIGN KEY(lead_id) REFERENCES public.leads (id) ON DELETE CASCADE,
	UNIQUE (active_lead_id),
	FOREIGN KEY(active_lead_id) REFERENCES public.leads (id) ON DELETE CASCADE
);


DO $security$
DECLARE table_name text; api_role text; role_sql text; columns_sql text; target oid;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['lead_website_qualifications','website_qualification_jobs','website_qualification_items'] LOOP
  target := to_regclass('public.' || table_name);
  IF NOT EXISTS(SELECT FROM pg_class WHERE oid=target AND relkind='r' AND NOT relispartition
      AND relowner=(SELECT oid FROM pg_roles WHERE rolname='postgres'))
      OR EXISTS(SELECT FROM pg_policy WHERE polrelid=target)
      OR EXISTS(SELECT FROM pg_inherits WHERE inhparent=target OR inhrelid=target) THEN
   RAISE EXCEPTION 'Review website qualification ownership, policies or inheritance';
  END IF;
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
  EXECUTE format('GRANT ALL ON TABLE public.%I TO postgres', table_name);
  SELECT string_agg(quote_ident(attname),', ' ORDER BY attnum) INTO columns_sql
   FROM pg_attribute WHERE attrelid=target AND attnum>0 AND NOT attisdropped;
  FOREACH api_role IN ARRAY ARRAY['PUBLIC','anon','authenticated'] LOOP
   IF api_role <> 'PUBLIC' AND NOT EXISTS(SELECT FROM pg_roles WHERE rolname=api_role) THEN CONTINUE; END IF;
   role_sql := CASE WHEN api_role='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(api_role) END;
   EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %s RESTRICT',table_name,role_sql);
   EXECUTE format('REVOKE ALL PRIVILEGES (%s) ON TABLE public.%I FROM %s RESTRICT',columns_sql,table_name,role_sql);
  END LOOP;
  FOR api_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
   IF has_table_privilege(api_role,target,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
      OR has_any_column_privilege(api_role,target,'SELECT,INSERT,UPDATE,REFERENCES') THEN
    RAISE EXCEPTION 'Website qualification privileges remain; review inherited grants';
   END IF;
  END LOOP;
 END LOOP;
END $security$;
COMMIT;
