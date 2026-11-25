"""Schema and handoff validation; only private release metadata may be written."""
from sqlalchemy import select

from backend.database import Base, engine


def validate_deployment_schema():
    from backend import models  # noqa: F401

    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        for table in Base.metadata.sorted_tables:
            connection.execute(select(table).limit(0))
    if engine.dialect.name == "postgresql":
        # Close the gap between the gate's commit and Swarm stopping the legacy
        # process. No legacy request can run once this replacement starts under
        # stop-first ordering. Only private release metadata is written here.
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout='10s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout='30s'")
            state = connection.exec_driver_sql("""SELECT legacy_handoff_complete,verified_server_search_ids
                FROM public.gmapscrap_schema_migrations
                WHERE filename='20261124_desktop_execution.sql' FOR UPDATE""").one()
            if not state.legacy_handoff_complete:
                connection.exec_driver_sql("LOCK TABLE public.search_runs IN SHARE MODE")
                active = set(connection.exec_driver_sql("""SELECT id FROM public.search_runs
                    WHERE status IN ('queued','running','paused') AND execution_source='server'""").scalars())
                if not active.issubset(set(state.verified_server_search_ids)):
                    raise RuntimeError("Unreviewed legacy active searches; startup stopped before schedulers")
                connection.exec_driver_sql("""UPDATE public.gmapscrap_schema_migrations
                    SET legacy_handoff_complete=true WHERE filename='20261124_desktop_execution.sql'""")
