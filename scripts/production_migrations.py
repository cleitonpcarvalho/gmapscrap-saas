"""Fail-closed production gate. Never imports/runs application startup DDL.

Runs in Dockerfile.migrations as a non-root user. PG* variables come directly
from the existing backend, never from new credentials or command-line secrets.
Only the versioned release allowlist can be executed; historical security SQL is excluded.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATIONS = ("20261124_crm_company_profiles.sql", "20261124_desktop_execution.sql", "20261125_website_qualification.sql")
QUALIFICATION_TABLES = ("lead_website_qualifications", "website_qualification_jobs", "website_qualification_items")
LEDGER = "gmapscrap_schema_migrations"
SECURED = ("leads", "search_runs", "tags", "lead_tags", "niches", "crm_leads",
           "crm_funnels", "crm_funnel_stages", "crm_stage_history", "crm_activities", "crm_follow_ups")


class GateError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def run(command, *, env=None, stdout=subprocess.PIPE):
    # Never echo commands, stderr, SQL errors, rows, URLs, or process environments.
    result = subprocess.run(command, env=env, stdout=stdout, stderr=subprocess.PIPE)
    require(result.returncode == 0, f"{Path(command[0]).name} failed; deployment stopped")
    return result.stdout


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migration_body(name):
    require(name in MIGRATIONS, "Migration outside release allowlist")
    script = (ROOT / "migrations" / name).read_text()
    require(len(re.findall(r"^BEGIN;\s*$", script, re.M)) == 1, "Unexpected migration transaction")
    require(len(re.findall(r"^COMMIT;\s*$", script, re.M)) == 1, "Unexpected migration transaction")
    # Both migrations and their ledger entries commit as ONE transaction.
    script = re.sub(r"^BEGIN;\s*$", "", script, count=1, flags=re.M)
    return re.sub(r"^COMMIT;\s*$", "", script, count=1, flags=re.M)


def scalar(connection, query, parameters=()):
    return connection.execute(query, parameters).fetchone()[0]


def columns(connection, table):
    return {row[0]: (row[1], row[2], row[3]) for row in connection.execute("""
        SELECT attname, format_type(atttypid,atttypmod), attnotnull,
               pg_get_expr(d.adbin,d.adrelid)
        FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=to_regclass(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
        """, (f"public.{table}",))}


def table_exists(connection, table):
    return scalar(connection, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))


def assert_security(connection, table):
    state = connection.execute("""SELECT c.relkind,c.relrowsecurity,c.relforcerowsecurity,
        pg_get_userbyid(c.relowner), (SELECT count(*) FROM pg_policy WHERE polrelid=c.oid),
        EXISTS(SELECT FROM pg_inherits WHERE inhrelid=c.oid OR inhparent=c.oid)
        FROM pg_class c WHERE c.oid=to_regclass(%s)""", (f"public.{table}",)).fetchone()
    require(state == ("r", True, False, "postgres", 0, False), f"Unexpected security/ownership on {table}")
    require(not scalar(connection, """SELECT EXISTS(SELECT FROM pg_class c,
        LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE c.oid=to_regclass(%s) AND a.grantee=0)""", (f"public.{table}",)), f"PUBLIC table access: {table}")
    require(not scalar(connection, """SELECT EXISTS(SELECT FROM pg_attribute c,
        LATERAL aclexplode(c.attacl) a WHERE c.attrelid=to_regclass(%s) AND a.grantee=0)""",
        (f"public.{table}",)), f"PUBLIC column access: {table}")
    for role in ("anon", "authenticated"):
        require(scalar(connection, "SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=%s)", (role,)), "Missing API role")
        exposed = scalar(connection, """SELECT has_table_privilege(%s,to_regclass(%s),
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR
            has_any_column_privilege(%s,to_regclass(%s),'SELECT,INSERT,UPDATE,REFERENCES')""",
            (role, f"public.{table}", role, f"public.{table}"))
        require(not exposed, f"API access remains on {table}")
    for (sequence,) in connection.execute("""SELECT s.oid FROM pg_class s JOIN pg_depend d
        ON d.classid='pg_class'::regclass AND d.objid=s.oid AND d.refclassid='pg_class'::regclass
        WHERE s.relkind='S' AND d.refobjid=to_regclass(%s) AND d.deptype IN ('a','i')""", (f"public.{table}",)):
        require(not scalar(connection, """SELECT EXISTS(SELECT FROM pg_class c,
            LATERAL aclexplode(coalesce(c.relacl,acldefault('s',c.relowner))) a
            WHERE c.oid=%s AND a.grantee=0)""", (sequence,)), f"PUBLIC sequence access on {table}")
        for role in ("anon", "authenticated"):
            require(not scalar(connection, "SELECT has_sequence_privilege(%s,%s,'USAGE,SELECT,UPDATE')", (role, sequence)), f"API sequence access on {table}")
    require(scalar(connection, "SELECT has_table_privilege('postgres',to_regclass(%s),'SELECT,INSERT,UPDATE,DELETE')",
                   (f"public.{table}",)), f"Backend owner lacks access to {table}")


def installed(connection, name):
    if name == MIGRATIONS[2]:
        present = [table_exists(connection, table) for table in QUALIFICATION_TABLES]
        if not any(present): return False
        require(all(present), "Partially installed website qualification migration")
        from backend.database import Base
        from backend import models
        from sqlalchemy.dialects import postgresql
        for table in QUALIFICATION_TABLES:
            model = Base.metadata.tables[table]
            expected = {}
            for column in model.columns:
                kind = str(column.type.compile(dialect=postgresql.dialect())).lower().replace("varchar", "character varying")
                expected[column.name] = (kind, not column.nullable, str(column.server_default.arg) if column.server_default else None)
            require(columns(connection, table) == expected, "Website qualification columns/defaults drift")
            constraints = connection.execute("""SELECT contype,conkey::text,confkey::text,
                confrelid::regclass::text,confdeltype,convalidated FROM pg_constraint
                WHERE conrelid=to_regclass(%s) ORDER BY contype,conkey::text""", ("public." + table,)).fetchall()
            expected_count = {QUALIFICATION_TABLES[0]: 6, QUALIFICATION_TABLES[1]: 2, QUALIFICATION_TABLES[2]: 7}[table]
            require(len(constraints) == expected_count and all(row[5] for row in constraints), "Website qualification constraints drift")
            def normalized(definition):
                definition = re.sub(r"::(?:character varying|text)(?:\[\])?", "", definition)
                return re.sub(r"[\s()]+", "", definition.replace("public.", ""))
            expected_definitions = {
                QUALIFICATION_TABLES[0]: ["PRIMARY KEY (lead_id)", "FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE",
                    "CHECK (cms = ANY (ARRAY['WordPress','other','unknown']))", "CHECK (priority = ANY (ARRAY['HIGH','MEDIUM','LOW','INCONCLUSIVE']))",
                    "CHECK (total_posts IS NULL OR total_posts >= 0)", "CHECK (days_since_publication IS NULL OR days_since_publication >= 0)"],
                QUALIFICATION_TABLES[1]: ["PRIMARY KEY (id)", "CHECK (status = ANY (ARRAY['queued','running','completed']))"],
                QUALIFICATION_TABLES[2]: ["PRIMARY KEY (job_id,lead_id)", "UNIQUE (active_lead_id)",
                    "FOREIGN KEY (job_id) REFERENCES website_qualification_jobs(id) ON DELETE CASCADE",
                    "FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE", "FOREIGN KEY (active_lead_id) REFERENCES leads(id) ON DELETE CASCADE",
                    "CHECK (status = ANY (ARRAY['queued','running','completed','failed']))", "CHECK (active_lead_id IS NULL OR active_lead_id = lead_id)"]}
            definitions = [r[0] for r in connection.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=to_regclass(%s)", ("public."+table,))]
            require({normalized(d) for d in definitions} == {normalized(d) for d in expected_definitions[table]}, "Website qualification constraint definition drift")
            require(not scalar(connection, "SELECT EXISTS(SELECT FROM pg_index WHERE indrelid=to_regclass(%s) AND (NOT indisvalid OR NOT indisready))", ("public."+table,)), "Website qualification index invalid")
            foreign_keys = [row for row in constraints if row[0] == "f"]
            expected_targets = {QUALIFICATION_TABLES[0]: ["leads"], QUALIFICATION_TABLES[1]: [],
                                QUALIFICATION_TABLES[2]: ["leads", "leads", "website_qualification_jobs"]}[table]
            require(sorted(row[3].removeprefix("public.") for row in foreign_keys) == expected_targets
                    and all(row[4] == "c" for row in foreign_keys), "Website qualification foreign keys drift")
            assert_security(connection, table)
        return True
    if name == MIGRATIONS[0]:
        if not table_exists(connection, "crm_company_profiles"):
            return False
        expected = {"lead_id": ("integer", True), "niche_override": ("character varying(255)", False),
                    "location_override": ("character varying(255)", False), "contact_name": ("character varying(255)", False),
                    "contact_phone": ("character varying(80)", False), "contact_email": ("character varying(255)", False),
                    "version": ("integer", True), "updated_at": ("timestamp with time zone", True)}
        actual = columns(connection, "crm_company_profiles")
        require({k: v[:2] for k, v in actual.items()} == expected, "Company profile schema drift")
        require(actual["version"][2] == "1" and actual["updated_at"][2] == "now()", "Company profile defaults drift")
        constraints = connection.execute("""SELECT contype,pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid='public.crm_company_profiles'::regclass""").fetchall()
        require(len(constraints) == 3 and {r[0] for r in constraints} == {"p", "f", "c"}, "Company profile constraints drift")
        require(any(r[1] == "PRIMARY KEY (lead_id)" for r in constraints), "Company profile primary key drift")
        require(any(re.fullmatch(r"FOREIGN KEY \(lead_id\) REFERENCES (public\.)?leads\(id\) ON DELETE CASCADE", r[1]) for r in constraints), "Company profile foreign key drift")
        require(any(r[1] == "CHECK ((version >= 1))" for r in constraints), "Company profile version check drift")
        assert_security(connection, "crm_company_profiles")
        return True
    actual = columns(connection, "search_runs")
    present = {"execution_source", "desktop_request_id"}.intersection(actual)
    index = connection.execute("""SELECT i.indisunique,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)
        FROM pg_index i WHERE i.indexrelid=to_regclass('public.uq_search_runs_desktop_request_id')""").fetchone()
    if not present and index is None:
        return False
    require(present == {"execution_source", "desktop_request_id"}, "Partially installed desktop migration")
    require(actual["execution_source"] == ("character varying(20)", True, "'server'::character varying"), "Execution source schema drift")
    require(actual["desktop_request_id"] == ("character varying(64)", False, None), "Desktop request schema drift")
    require(index is not None and index[:3] == (True, True, True) and
            re.fullmatch(r"CREATE UNIQUE INDEX uq_search_runs_desktop_request_id ON public.search_runs USING btree \(desktop_request_id\)", index[3]), "Desktop unique index drift")
    return True


def migration_state(connection):
    entries = {}
    if table_exists(connection, LEDGER):
        assert_security(connection, LEDGER)
        entries = dict(connection.execute(sql.SQL("SELECT filename,sha256 FROM public.{}").format(sql.Identifier(LEDGER))))
        require(set(entries).issubset(MIGRATIONS), "Unknown ledger migration; review required")
    state = {}
    for name in MIGRATIONS:
        exists = installed(connection, name)
        if name in entries:
            require(entries[name] == checksum(ROOT / "migrations" / name), "Applied migration checksum changed")
            require(exists, "Ledger disagrees with live schema")
        if name == MIGRATIONS[2] and exists and name not in entries:
            raise GateError("Unrecorded qualification tables require review; never silently adopt derived data")
        state[name] = "recorded" if name in entries else "adopt" if exists else "pending"
    return state


def preflight(connection, verified_server_ids):
    require(scalar(connection, "SELECT current_user") == "postgres", "Requires existing effective postgres owner")
    require(int(scalar(connection, "SHOW server_version_num")) // 10000 == 17, "Backup/restore image must match production PostgreSQL major")
    for table in SECURED:
        assert_security(connection, table)
    require({"managed_manually", "estimated_value", "currency", "sales_outcome", "lost_reason", "closed_at", "version"}.issubset(columns(connection, "crm_leads")), "Manual CRM prerequisite missing")
    state = migration_state(connection)
    # Match startup's runnable states exactly. Paused rows are never submitted
    # by startup and need no ownership inference or record changes to deploy.
    if state[MIGRATIONS[1]] != "recorded" or os.getenv("GMAPSCRAP_LEGACY_BACKEND") == "1":
        known = set(verified_server_ids)
        if state[MIGRATIONS[1]] == "recorded":
            known.update(scalar(connection, sql.SQL("SELECT verified_server_search_ids FROM public.{} WHERE filename=%s").format(sql.Identifier(LEDGER)), (MIGRATIONS[1],)))
        source_filter = " AND execution_source='server'" if state[MIGRATIONS[1]] != "pending" else ""
        active = {r[0] for r in connection.execute("SELECT id FROM public.search_runs WHERE status IN ('queued','running')" + source_filter)}
        require(active.issubset(known), "Unreviewed legacy active searches; deployment stopped")
    return state


def snapshot(connection, layout=None):
    if layout is None:
        names = [r[0] for r in connection.execute("""SELECT tablename FROM pg_tables
            WHERE schemaname='public' ORDER BY tablename""") if r[0] != LEDGER]
        layout = {name: list(columns(connection, name)) for name in names}
    output = {}
    for table, names in layout.items():
        fields = sql.SQL(",").join(map(sql.Identifier, names))
        query = sql.SQL("SELECT row_to_json(t)::text FROM (SELECT {} FROM public.{}) t ORDER BY row_to_json(t)::text COLLATE \"C\"").format(fields, sql.Identifier(table))
        digest, count = hashlib.sha256(), 0
        with connection.cursor(name="preservation_snapshot") as cursor:
            cursor.execute(query)
            for (row,) in cursor:
                digest.update(row.encode() + b"\n")
                count += 1
        output[table] = {"rows": count, "sha256": digest.hexdigest()}
    return layout, output


def security_snapshot(connection, layout):
    result = {}
    for table, names in layout.items():
        result[table] = connection.execute("""SELECT relowner,relacl::text,relrowsecurity,relforcerowsecurity
            FROM pg_class WHERE oid=to_regclass(%s)""", (f"public.{table}",)).fetchone()
        result[table + ":columns"] = connection.execute("""SELECT attname,attacl::text FROM pg_attribute
            WHERE attrelid=to_regclass(%s) AND attname=ANY(%s) ORDER BY attname""", (f"public.{table}", names)).fetchall()
    result["defaults"] = connection.execute("SELECT defaclrole,defaclnamespace,defaclobjtype,defaclacl::text FROM pg_default_acl ORDER BY oid").fetchall()
    result["sequences"] = []
    for (sequence,) in connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"):
        value = connection.execute(sql.SQL("SELECT last_value,is_called FROM public.{}").format(sql.Identifier(sequence))).fetchone()
        result["sequences"].append((sequence, value))
    return result


def backend_schema(connection):
    from backend.database import Base
    from backend import models  # noqa: F401

    for table in Base.metadata.sorted_tables:
        connection.execute(sql.SQL("SELECT {} FROM public.{} LIMIT 0").format(
            sql.SQL(",").join(sql.Identifier(c.name) for c in table.columns), sql.Identifier(table.name)))


def apply_pending(connection, release, backup_sha, verified_server_ids):
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout='10s'")
        connection.execute("SET LOCAL statement_timeout='120s'")
        require(scalar(connection, "SELECT pg_try_advisory_xact_lock(731159714088)") is True, "Another migration is running")
        layout, _ = snapshot(connection)
        # Briefly block writers during the preservation comparison; readers continue.
        connection.execute(sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
            sql.SQL(",").join(sql.Identifier("public", name) for name in sorted(layout))))
        state = preflight(connection, verified_server_ids)
        _, before = snapshot(connection, layout)
        permissions = security_snapshot(connection, layout)
        if not table_exists(connection, LEDGER):
            connection.execute(sql.SQL("""CREATE TABLE public.{} (
                filename text PRIMARY KEY, sha256 text NOT NULL, release_sha text NOT NULL,
                backup_sha256 text NOT NULL, verified_server_search_ids integer[] NOT NULL DEFAULT '{{}}',
                legacy_handoff_complete boolean NOT NULL DEFAULT false,
                applied_at timestamptz NOT NULL DEFAULT now());
                ALTER TABLE public.{} ENABLE ROW LEVEL SECURITY;
                REVOKE ALL ON public.{} FROM PUBLIC,anon,authenticated""").format(*[sql.Identifier(LEDGER)] * 3))
        for name, status in state.items():
            if status == "recorded":
                if name == MIGRATIONS[1] and verified_server_ids:
                    previous = scalar(connection, sql.SQL("SELECT verified_server_search_ids FROM public.{} WHERE filename=%s").format(sql.Identifier(LEDGER)), (name,))
                    connection.execute(sql.SQL("UPDATE public.{} SET verified_server_search_ids=%s WHERE filename=%s").format(sql.Identifier(LEDGER)),
                                       (sorted(set(previous) | verified_server_ids), name))
                continue
            if status == "pending":
                connection.execute("SET LOCAL search_path=public,pg_catalog")
                connection.execute(migration_body(name), prepare=False)
            require(installed(connection, name), "Migration postcondition failed")
            connection.execute(sql.SQL("INSERT INTO public.{} (filename,sha256,release_sha,backup_sha256,verified_server_search_ids) VALUES (%s,%s,%s,%s,%s)").format(sql.Identifier(LEDGER)),
                               (name, checksum(ROOT / "migrations" / name), release, backup_sha, sorted(verified_server_ids) if name == MIGRATIONS[1] else []))
        connection.execute("SET LOCAL search_path=public,pg_catalog")
        backend_schema(connection)
        for table in (*SECURED, "crm_company_profiles", *QUALIFICATION_TABLES, LEDGER):
            assert_security(connection, table)
        require(snapshot(connection, layout)[1] == before, "Existing application rows changed; transaction aborted")
        require(security_snapshot(connection, layout) == permissions, "Existing permissions/defaults/sequences changed; transaction aborted")
        return state


@contextmanager
def restored_public(archive, roles):
    with tempfile.TemporaryDirectory(prefix="gmapscrap-restore-") as temporary:
        folder = Path(temporary)
        data, socket = folder / "data", folder / "socket"
        socket.mkdir()
        # Explicit local parameters on EVERY operation, never inherited production PG*.
        local_env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        local_env.update(PGHOST=str(socket), PGPORT="55489", PGUSER="restore_admin", PGDATABASE="postgres", PGSSLMODE="disable")
        run(["initdb", "-D", str(data), "-U", "restore_admin", "--auth=trust", "--no-locale", "--encoding=UTF8"], env=local_env)
        started = False
        try:
            run(["pg_ctl", "-D", str(data), "-l", str(folder / "postgres.log"), "-o", f"-k {socket} -p 55489 -c listen_addresses=''", "-w", "start"], env=local_env)
            started = True
            with psycopg.connect(host=str(socket), port=55489, user="restore_admin", dbname="postgres", sslmode="disable", autocommit=True) as admin:
                for role in roles:
                    if role not in {"restore_admin", "PUBLIC"} and not role.startswith("pg_"):
                        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(sql.Identifier(role)))
                admin.execute("CREATE DATABASE gmapscrap_restore OWNER postgres")
            local_env["PGDATABASE"] = "gmapscrap_restore"
            with psycopg.connect(host=str(socket), port=55489, user="restore_admin", dbname="gmapscrap_restore", sslmode="disable", autocommit=True) as admin:
                # --schema=public selects its contents, not the schema TOC entry.
                admin.execute("ALTER SCHEMA public OWNER TO postgres")
            run(["pg_restore", "--exit-on-error", "--single-transaction", "--schema=public", "--dbname=gmapscrap_restore", str(archive)], env=local_env)
            with psycopg.connect(host=str(socket), port=55489, user="restore_admin", dbname="gmapscrap_restore", sslmode="disable", autocommit=True) as restored:
                restored.execute("SET ROLE postgres")
                yield restored, socket
        finally:
            if started:
                run(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"], env=local_env)


def api_compatibility(socket):
    # In-process API reads against ONLY the disposable restored database. No startup,
    # schedulers, providers, or production HTTP requests are executed here.
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import Session
    from backend import main
    from backend.auth import COOKIE_NAME, create_session_token
    from backend.database import get_db

    test_engine = create_engine(URL.create("postgresql+psycopg", username="restore_admin", host=str(socket), port=55489, database="gmapscrap_restore", query={"options": "-crole=postgres"}))
    def read_only_db():
        with Session(test_engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout='30s'"))
            yield session
    main.app.dependency_overrides[get_db] = read_only_db
    client = TestClient(main.app)
    try:
        client.cookies.set(COOKIE_NAME, create_session_token(main.settings.app_username))
        for endpoint in ("/api/leads?limit=1", "/api/website-qualification/results?limit=1", "/api/crm/funnels", "/api/crm/leads", "/api/crm/manual/leads?limit=1", "/api/crm/manual/follow-ups", "/api/niches", "/api/searches"):
            require(client.get(endpoint).status_code == 200, "Restored backend API compatibility failed")
        funnels = client.get("/api/crm/funnels").json()
        for funnel in funnels:
            require(client.get(f"/api/crm/manual/cards?funnel_id={funnel['id']}").status_code == 200, "Restored CRM cards compatibility failed")
    finally:
        client.close()
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def gate(backup_dir, release, verified_server_ids):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release)), "Release must be a full commit SHA")
    host = os.environ.get("PGHOST", "")
    require(host.endswith((".supabase.com", ".supabase.co")), "Refusing a non-Supabase production target")
    require(os.environ.get("PGSSLMODE") in {"require", "verify-ca", "verify-full"}, "Production TLS is required")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = backup_dir / "production.dump"
    require(not archive.exists(), "Refusing to overwrite a production backup")
    # No credentials are placed in manifests or logged by subprocesses.
    with psycopg.connect(connect_timeout=15, autocommit=True) as production:
        with production.transaction():
            production.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            production.execute("SET LOCAL statement_timeout='120s'")
            state = preflight(production, verified_server_ids)
            require(scalar(production, "SELECT current_database()") == os.environ["PGDATABASE"], "Database identity mismatch")
            layout, before = snapshot(production)
            roles = [r[0] for r in production.execute("SELECT rolname FROM pg_roles")]
            exported = scalar(production, "SELECT pg_export_snapshot()")
            run(["pg_dump", "--format=custom", "--no-password", "--lock-wait-timeout=10s", f"--snapshot={exported}", f"--file={archive}"])
        archive.chmod(0o600)
        run(["pg_restore", "--list", str(archive)])
        with open(os.devnull, "wb") as destination:
            run(["pg_restore", "--file=-", str(archive)], stdout=destination)
        backup_sha = checksum(archive)
        # The full database archive is retained. A real application-schema restore
        # validates every existing public row, original owner, and ACL, then rehearses
        # migrations and the matching backend before ANY production DDL is allowed.
        with restored_public(archive, roles) as (restored, socket):
            with restored.transaction():
                require(snapshot(restored, layout)[1] == before, "Backup restore differs from exported production snapshot")
            apply_pending(restored, release, backup_sha, verified_server_ids)
            api_compatibility(socket)
        require(checksum(archive) == backup_sha, "Backup archive changed during validation")
        applied = apply_pending(production, release, backup_sha, verified_server_ids)
        with production.transaction():
            production.execute("SET TRANSACTION READ ONLY")
            require(all(value == "recorded" for value in migration_state(production).values()), "Post-commit migration check failed")
        evidence = {"release": release, "backup_sha256": backup_sha, "full_archive_read": True,
                    "public_schema_restore": True, "restored_backend_api": True,
                    "migrations_before": state, "migrations_applied": applied,
                    "existing_rows_preserved": True, "existing_security_preserved": True,
                    "backup_snapshot_counts": {name: item["rows"] for name, item in before.items()},
                    "completed_at": datetime.now(timezone.utc).isoformat()}
        (backup_dir / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        (backup_dir / "evidence.json").chmod(0o600)
        print(json.dumps(evidence), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--backup-dir", type=Path, default=Path("/backup"))
    parser.add_argument("--verified-server-search-ids", default="")
    args = parser.parse_args()
    require(bool(re.fullmatch(r"(?:[0-9]+(?:,[0-9]+)*)?", args.verified_server_search_ids)), "Invalid verified search IDs")
    verified = {int(value) for value in args.verified_server_search_ids.split(",") if value}
    gate(args.backup_dir, args.release, verified)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, GateError) else f"Migration gate failed ({type(error).__name__}); no deployment permitted", file=sys.stderr)
        sys.exit(1)
