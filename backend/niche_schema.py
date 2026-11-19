"""Supabase Data API roles must use the authenticated GmapScrap backend."""

NICHE_ACCESS_SQL = """
ALTER TABLE niches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE niches FROM PUBLIC;
REVOKE ALL ON SEQUENCE niches_id_seq FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON TABLE niches FROM anon;
        REVOKE ALL ON SEQUENCE niches_id_seq FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE niches FROM authenticated;
        REVOKE ALL ON SEQUENCE niches_id_seq FROM authenticated;
    END IF;
END $$;
"""


def protect_niche_table(target, connection, **kwargs) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(NICHE_ACCESS_SQL)
