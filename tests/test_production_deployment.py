"""Release safety regressions. PostgreSQL fixtures use disposable loopback DBs."""
import os

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import main
from scripts import production_migrations as migration
from test_postgres_crm_security import PHASE1, SECURITY, data_snapshot, postgres, run_script

RELEASE = "a" * 40
BACKUP = "b" * 64


@pytest.fixture
def pending(postgres):
    run_script(postgres, PHASE1)
    run_script(postgres, SECURITY)
    with postgres.begin() as c:
        c.exec_driver_sql("DROP TABLE public.crm_company_profiles")
        c.exec_driver_sql("ALTER TABLE public.search_runs DROP COLUMN execution_source, DROP COLUMN desktop_request_id")
        for table in migration.SECURED:
            c.exec_driver_sql(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            c.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM PUBLIC,anon,authenticated")
    configured = make_url(os.environ["GMAPSCRAP_TEST_POSTGRES_URL"])
    with psycopg.connect(host=configured.host, port=configured.port, user=configured.username,
                         password=configured.password, dbname=postgres.url.database, autocommit=True) as c:
        c.execute("SET ROLE postgres")
        yield c, postgres


@pytest.mark.postgres
def test_pending_only_atomic_idempotent_and_preserves_rows_and_permissions(pending, monkeypatch):
    c, engine = pending
    before = data_snapshot(engine)
    with c.transaction():
        assert set(migration.preflight(c, set()).values()) == {"pending"}
    executed = []
    original = migration.migration_body
    def only_pending(name):
        executed.append(name)
        return original(name)
    monkeypatch.setattr(migration, "migration_body", only_pending)
    migration.apply_pending(c, RELEASE, BACKUP, set())
    assert executed == list(migration.MIGRATIONS)
    after = data_snapshot(engine)
    assert after.pop("crm_company_profiles") == []
    assert len(after.pop(migration.LEDGER)) == 2
    # Only additive search fields differ; every original value is identical.
    with c.transaction():
        layout = {name: list(migration.columns(c, name)) for name in before}
        layout["search_runs"] = [name for name in layout["search_runs"] if name not in {"execution_source", "desktop_request_id"}]
        assert migration.snapshot(c, layout)[1]
        migration.backend_schema(c)
    import json
    for name in before:
        old = [json.loads(row) for row in before[name]]
        new = [json.loads(row) for row in after[name]]
        if name == "search_runs":
            for row in new:
                assert row.pop("execution_source") == "server"
                assert row.pop("desktop_request_id") is None
        assert new == old
    migration.apply_pending(c, RELEASE, BACKUP, set())
    assert executed == list(migration.MIGRATIONS)  # no SQL reapplication


@pytest.mark.postgres
def test_second_migration_failure_rolls_back_first_and_ledger(pending, monkeypatch):
    c, engine = pending
    before = data_snapshot(engine)
    original = migration.migration_body
    monkeypatch.setattr(migration, "migration_body", lambda name: "SELECT 1/0" if name == migration.MIGRATIONS[1] else original(name))
    with pytest.raises(psycopg.errors.DivisionByZero):
        migration.apply_pending(c, RELEASE, BACKUP, set())
    assert data_snapshot(engine) == before
    assert not migration.table_exists(c, migration.LEDGER)
    assert not migration.table_exists(c, "crm_company_profiles")


@pytest.mark.postgres
def test_legacy_active_ownership_blocks_without_any_mutation(pending):
    c, engine = pending
    c.execute("UPDATE public.search_runs SET status='paused'")
    before = data_snapshot(engine)
    with pytest.raises(migration.GateError, match="Unreviewed legacy"):
        migration.apply_pending(c, RELEASE, BACKUP, set())
    assert data_snapshot(engine) == before
    ids = {r[0] for r in c.execute("SELECT id FROM public.search_runs")}
    migration.apply_pending(c, RELEASE, BACKUP, ids)
    assert c.execute("SELECT DISTINCT status,execution_source FROM public.search_runs").fetchall() == [("paused", "server")]


@pytest.mark.postgres
def test_legacy_backend_cannot_create_unreviewed_work_after_preparation(pending, monkeypatch):
    c, engine = pending
    monkeypatch.setenv("GMAPSCRAP_LEGACY_BACKEND", "1")
    c.execute("UPDATE public.search_runs SET status='paused'")
    ids = {r[0] for r in c.execute("SELECT id FROM public.search_runs")}
    migration.apply_pending(c, RELEASE, BACKUP, ids)
    migration.apply_pending(c, RELEASE, BACKUP, set())  # retained verified IDs
    from backend.models import SearchRun
    with Session(engine) as session:
        session.add(SearchRun(niche="Synthetic", location="Local", status="paused"))
        session.commit()
    before = data_snapshot(engine)
    with pytest.raises(migration.GateError, match="Unreviewed legacy"):
        migration.apply_pending(c, RELEASE, BACKUP, set())
    assert data_snapshot(engine) == before
    new_ids = {r[0] for r in c.execute("SELECT id FROM public.search_runs")} - ids
    migration.apply_pending(c, RELEASE, BACKUP, new_ids)
    retained = c.execute(f"SELECT verified_server_search_ids FROM public.{migration.LEDGER} WHERE filename=%s", (migration.MIGRATIONS[1],)).fetchone()[0]
    assert set(retained) == ids | new_ids


@pytest.mark.postgres
def test_startup_closes_legacy_handoff_race_without_changing_searches(pending, monkeypatch):
    from backend import deployment_schema
    c, engine = pending
    migration.apply_pending(c, RELEASE, BACKUP, set())
    c.execute("UPDATE public.search_runs SET status='paused'")  # Legacy request after gate commit.
    before = data_snapshot(engine)
    monkeypatch.setattr(deployment_schema, "engine", engine)
    with pytest.raises(RuntimeError, match="Unreviewed legacy"):
        deployment_schema.validate_deployment_schema()
    assert data_snapshot(engine) == before
    ids = [r[0] for r in c.execute("SELECT id FROM public.search_runs")]
    c.execute(f"UPDATE public.{migration.LEDGER} SET verified_server_search_ids=%s WHERE filename=%s", (ids, migration.MIGRATIONS[1]))
    deployment_schema.validate_deployment_schema()
    assert c.execute(f"SELECT legacy_handoff_complete FROM public.{migration.LEDGER} WHERE filename=%s", (migration.MIGRATIONS[1],)).fetchone() == (True,)
    assert data_snapshot(engine)["search_runs"] == before["search_runs"]
    # Subsequent restarts allow correctly classified work created by the new backend.
    c.execute(f"UPDATE public.{migration.LEDGER} SET verified_server_search_ids='{{}}'")
    deployment_schema.validate_deployment_schema()


@pytest.mark.postgres
def test_partial_schema_or_changed_checksum_stops_before_writes(pending):
    c, engine = pending
    c.execute("ALTER TABLE public.search_runs ADD COLUMN desktop_request_id varchar(64)")
    before = data_snapshot(engine)
    with pytest.raises(migration.GateError, match="Partially installed"):
        migration.apply_pending(c, RELEASE, BACKUP, set())
    assert data_snapshot(engine) == before
    c.execute("ALTER TABLE public.search_runs DROP COLUMN desktop_request_id")
    migration.apply_pending(c, RELEASE, BACKUP, set())
    c.execute(f"UPDATE public.{migration.LEDGER} SET sha256='drift'")
    before = data_snapshot(engine)
    with pytest.raises(migration.GateError, match="checksum changed"):
        migration.apply_pending(c, RELEASE, BACKUP, set())
    assert data_snapshot(engine) == before


@pytest.mark.postgres
def test_real_archive_restore_migration_and_matching_backend_reads(pending, tmp_path):
    c, engine = pending
    configured = make_url(os.environ["GMAPSCRAP_TEST_POSTGRES_URL"])
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    environment.update(PGHOST=configured.host, PGPORT=str(configured.port), PGUSER=configured.username,
                       PGDATABASE=engine.url.database, PGSSLMODE="disable")
    if configured.password:
        environment["PGPASSWORD"] = configured.password
    archive = tmp_path / "fixture.dump"
    with c.transaction():
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        layout, before = migration.snapshot(c)
        snapshot = migration.scalar(c, "SELECT pg_export_snapshot()")
        migration.run(["pg_dump", "--format=custom", f"--snapshot={snapshot}", f"--file={archive}"], env=environment)
        roles = [r[0] for r in c.execute("SELECT rolname FROM pg_roles")]
    original_sha = migration.checksum(archive)
    with migration.restored_public(archive, roles) as (restored, socket):
        with restored.transaction():
            assert migration.snapshot(restored, layout)[1] == before
        migration.apply_pending(restored, RELEASE, original_sha, set())
        migration.api_compatibility(socket)
    assert migration.checksum(archive) == original_sha
    assert not migration.table_exists(c, migration.LEDGER)  # source was only read
    assert not migration.table_exists(c, "crm_company_profiles")


def test_managed_startup_skips_legacy_ddl_and_fails_closed(monkeypatch):
    from backend import deployment_schema
    calls = []
    monkeypatch.setenv("GMAPSCRAP_SCHEMA_MANAGED", "1")
    monkeypatch.setattr(main, "_run_startup_migration_with_timeout", lambda *a: pytest.fail("Legacy DDL must not run"))
    monkeypatch.setattr(deployment_schema, "validate_deployment_schema", lambda: calls.append("validated"))
    for name in ("resume_unfinished_search_runs", "resume_running_email_campaigns", "start_email_campaign_scheduler", "resume_running_whatsapp_campaigns", "start_whatsapp_campaign_scheduler"):
        monkeypatch.setattr(main, name, lambda: calls.append("scheduler"))
    main.on_startup()
    assert calls[0] == "validated"
    calls.clear()
    def fail():
        raise RuntimeError("missing schema")
    monkeypatch.setattr(deployment_schema, "validate_deployment_schema", fail)
    with pytest.raises(RuntimeError, match="missing schema"):
        main.on_startup()
    assert calls == []


def test_only_approved_files_and_no_transaction_commit_in_body():
    for name in migration.MIGRATIONS:
        body = migration.migration_body(name)
        assert "\nCOMMIT;" not in body
        assert "\nBEGIN;" not in body
    with pytest.raises(migration.GateError, match="allowlist"):
        migration.migration_body("20261124_lead_security.sql")


def test_nonproduction_target_stops_before_backup_or_connection(monkeypatch, tmp_path):
    monkeypatch.setenv("PGHOST", "localhost")
    monkeypatch.setattr(migration.psycopg, "connect", lambda **kw: pytest.fail("Must not connect"))
    with pytest.raises(migration.GateError, match="non-Supabase"):
        migration.gate(tmp_path, RELEASE, set())
    assert list(tmp_path.iterdir()) == []


def test_failed_gate_never_updates_a_service_or_prints_credentials(monkeypatch, tmp_path, capsys):
    from scripts import production_release as release
    commands = []
    monkeypatch.setattr(release, "STATE", tmp_path / "release-state")
    monkeypatch.setattr(release, "task", lambda component: "synthetic-container")
    monkeypatch.setattr(release, "existing_credentials", lambda: {"PGPASSWORD": "test-secret-do-not-print"})
    monkeypatch.setattr(release.os, "chown", lambda *args: None)
    def fail_gate(command, **kwargs):
        commands.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            import json
            repository = command[3].rsplit(":", 1)[0]
            return json.dumps([{"Config": {"Labels": {"org.opencontainers.image.revision": RELEASE}}, "RepoDigests": [repository + "@sha256:" + "c" * 64]}]).encode()
        if "--entrypoint" in command:
            return b"999\n"
        if "--read-only" in command:
            assert kwargs["env"]["PGPASSWORD"] == "test-secret-do-not-print"
            raise RuntimeError("Migration prerequisite failed")
        return b""
    monkeypatch.setattr(release, "run", fail_gate)
    with pytest.raises(RuntimeError, match="prerequisite failed"):
        release.release_production(RELEASE, "deploy", "")
    assert all(command[:3] != ["docker", "service", "update"] for command in commands)
    assert "test-secret-do-not-print" not in str(commands)
    captured = capsys.readouterr()
    assert "test-secret-do-not-print" not in captured.out + captured.err
