"""Guard regressions on the disposable security_admin localhost:55489 cluster.

No production connection/settings are used. Existing migration fixtures create
and remove a fresh synthetic database for each PostgreSQL test.
"""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from scripts.lead_security_guard import (
    InvalidSchemaSnapshot, RENDER_SEARCH_PATH, SCHEMA_QUERIES, SNAPSHOT_FORMAT,
    SchemaMismatch, capture_application_schema, require_unchanged_application_schema,
)
from test_postgres_lead_security import (  # reuse the restricted, disposable fixture
    MIGRATION, assert_secured, fingerprints, metadata, secured_database,
)


@contextmanager
def connection(owner):
    with owner.connect().execution_options(isolation_level="AUTOCOMMIT") as wrapper:
        raw = wrapper.connection.driver_connection
        try:
            yield raw
        finally:
            raw.execute("ROLLBACK")


def legacy_schema(raw):
    """The old comparison read these categories under the caller's search_path."""
    result = {}
    for name in ("columns", "constraints", "indexes", "policies", "triggers"):
        cur = raw.execute(SCHEMA_QUERIES[name])
        result[name] = [dict(zip([d.name for d in cur.description], row)) for row in cur.fetchall()]
    return result


def trigger_fixture(raw):
    raw.execute("""
        CREATE FUNCTION public.guard_fixture() RETURNS trigger LANGUAGE plpgsql
        AS $$ BEGIN RETURN NEW; END $$;
        CREATE TRIGGER guard_fixture BEFORE UPDATE ON public.leads
        FOR EACH ROW EXECUTE FUNCTION public.guard_fixture();
        CREATE VIEW public.guard_fixture_view AS SELECT 'public.literal'::text AS value;
    """)


def guarded_apply(raw, *, change=None, precommit=None, after_preflight=None):
    """Same deferred-COMMIT ordering as the corrected production runner."""
    prefix, tail = MIGRATION.split("DO $security$", 1)
    body_tail, commit = tail.rsplit("$security$;", 1)
    body = "DO $security$" + body_tail + "$security$;"
    assert prefix + body + commit == MIGRATION and commit.strip() == "COMMIT;"
    raw.execute("BEGIN READ ONLY")
    before = capture_application_schema(raw)
    raw.execute("ROLLBACK")
    if after_preflight:
        after_preflight()
    try:
        raw.execute(prefix, prepare=False)
        require_unchanged_application_schema(before, capture_application_schema(raw))
        raw.execute(body, prepare=False)
        if change:
            raw.execute(change)
        require_unchanged_application_schema(before, capture_application_schema(raw))
        if precommit:
            precommit()
        raw.execute(commit, prepare=False)
    except BaseException:
        raw.execute("ROLLBACK")
        raise


@pytest.mark.postgres
def test_reproduces_legacy_false_positive_and_corrected_guard_commits(secured_database):
    owner, _, _ = secured_database
    with connection(owner) as raw:
        trigger_fixture(raw)
        raw.execute("SET search_path=public,pg_catalog")
        raw.execute("BEGIN READ ONLY")
        legacy_before = legacy_schema(raw)
        canonical_before = capture_application_schema(raw)
        raw.execute("ROLLBACK")
        prefix, tail = MIGRATION.split("DO $security$", 1)
        body_tail, _ = tail.rsplit("$security$;", 1)
        raw.execute(prefix, prepare=False)
        raw.execute("DO $security$" + body_tail + "$security$;", prepare=False)
        legacy_after = legacy_schema(raw)
        changed = {k for k in legacy_before if legacy_before[k] != legacy_after[k]}
        assert changed == {"columns", "constraints", "triggers"}
        require_unchanged_application_schema(canonical_before, capture_application_schema(raw))
        raw.execute("ROLLBACK")
        guarded_apply(raw)
    assert_secured(owner)


@pytest.mark.postgres
@pytest.mark.parametrize("path", ['public, pg_catalog', '"absent schema", public', 'pg_catalog'])
def test_capture_is_canonical_transaction_local_and_restores_caller_path(secured_database, path):
    owner, _, _ = secured_database
    with connection(owner) as raw:
        raw.execute("BEGIN")
        raw.execute("SELECT set_config('search_path',%s,true)", (path,))
        expected_path = raw.execute("SHOW search_path").fetchone()[0]
        raw.execute("CREATE TABLE public.guard_uncommitted(id integer)")
        first = capture_application_schema(raw)
        assert raw.execute("SHOW search_path").fetchone()[0] == expected_path
        assert raw.info.transaction_status == TransactionStatus.INTRANS
        raw.execute("SET LOCAL search_path=pg_catalog")
        require_unchanged_application_schema(first, capture_application_schema(raw))
        raw.execute("ROLLBACK")
        assert raw.execute("SELECT to_regclass('public.guard_uncommitted')").fetchone()[0] is None


@pytest.mark.postgres
def test_capture_refuses_idle_autocommit_and_does_not_mask_database_errors(secured_database, monkeypatch):
    owner, _, _ = secured_database
    with connection(owner) as raw:
        with pytest.raises(RuntimeError, match="active transaction"):
            capture_application_schema(raw)
        raw.execute("BEGIN")
        monkeypatch.setitem(SCHEMA_QUERIES, "columns", "SELECT missing_guard_column")
        with pytest.raises(psycopg.errors.UndefinedColumn):
            capture_application_schema(raw)
        assert raw.info.transaction_status == TransactionStatus.INERROR
        raw.execute("ROLLBACK")
        assert raw.execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.postgres
@pytest.mark.parametrize("change,category", [
    ("ALTER TABLE public.leads ADD COLUMN guard_new text", "columns"),
    ("ALTER TABLE public.leads ALTER COLUMN name TYPE varchar(600)", "columns"),
    ("ALTER TABLE public.leads ALTER COLUMN name DROP NOT NULL", "columns"),
    ("ALTER TABLE public.leads ALTER COLUMN name SET DEFAULT 'public.literal'", "columns"),
    ("ALTER TABLE public.leads ADD CONSTRAINT guard_check CHECK(char_length(name)>=0)", "constraints"),
    ("CREATE INDEX guard_index ON public.leads(name)", "indexes"),
    ("ALTER TABLE public.leads DISABLE TRIGGER guard_fixture", "triggers"),
    ("CREATE POLICY guard_policy ON public.leads FOR SELECT USING(false)", "policies"),
    ("CREATE TABLE public.guard_unexpected(id integer)", "tables"),
    ("CREATE VIEW public.guard_unexpected AS SELECT id FROM public.leads", "tables"),
    ("CREATE OR REPLACE FUNCTION public.guard_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$", "routines"),
    ("CREATE OR REPLACE VIEW public.guard_fixture_view AS SELECT 'literal'::text AS value", "views"),
    ("ALTER SEQUENCE public.leads_id_seq INCREMENT 2", "sequences"),
])
def test_real_schema_change_rolls_back_entire_security_migration(secured_database, change, category):
    owner, _, _ = secured_database
    with connection(owner) as raw:
        trigger_fixture(raw)
        raw.execute("BEGIN READ ONLY")
        structure_before = capture_application_schema(raw)
        raw.execute("ROLLBACK")
    rows_before, metadata_before = fingerprints(owner), metadata(owner)
    with connection(owner) as raw:
        with pytest.raises(SchemaMismatch) as error:
            guarded_apply(raw, change=change)
        assert category in error.value.categories
        assert raw.info.transaction_status == TransactionStatus.IDLE
        raw.execute("BEGIN READ ONLY")
        require_unchanged_application_schema(structure_before, capture_application_schema(raw))
        raw.execute("ROLLBACK")
    assert fingerprints(owner) == rows_before
    assert metadata(owner) == metadata_before


@pytest.mark.postgres
def test_schema_drift_after_preflight_is_rejected_before_migration(secured_database):
    owner, _, _ = secured_database
    with connection(owner) as raw:
        with pytest.raises(SchemaMismatch, match="columns"):
            guarded_apply(raw, after_preflight=lambda: raw.execute(
                "ALTER TABLE public.leads ADD COLUMN prior_independent_change text"))
        assert raw.info.transaction_status == TransactionStatus.IDLE
        # The independent change predates the migration transaction. Preserve it
        # while rejecting the stale preflight and leaving security unapplied.
        assert raw.execute("SELECT count(*) FROM pg_attribute WHERE attrelid='public.leads'::regclass AND attname='prior_independent_change'").fetchone()[0] == 1
        assert not raw.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.leads'::regclass").fetchone()[0]


@pytest.mark.postgres
def test_corrected_guard_repeatable_and_preserves_data_sequences_and_structure(secured_database):
    owner, _, _ = secured_database
    rows_before, metadata_before = fingerprints(owner), metadata(owner)
    with connection(owner) as raw:
        raw.execute("SET search_path=public,pg_catalog")
        snapshots = []
        for _ in range(2):
            guarded_apply(raw)
            assert raw.info.transaction_status == TransactionStatus.IDLE
            assert raw.execute("SHOW search_path").fetchone()[0] == "public, pg_catalog"
            raw.execute("BEGIN READ ONLY")
            snapshots.append(capture_application_schema(raw))
            raw.execute("ROLLBACK")
        require_unchanged_application_schema(*snapshots)
    assert_secured(owner)
    assert fingerprints(owner) == rows_before
    after = metadata(owner)
    for key in ("columns", "constraints", "indexes", "sequences", "roles"):
        assert after[key] == metadata_before[key]


@pytest.mark.postgres
@pytest.mark.parametrize("failure", ["sql", "other_integrity_guard"])
def test_other_errors_still_prevent_commit(secured_database, failure):
    owner, _, _ = secured_database
    rows_before, metadata_before = fingerprints(owner), metadata(owner)
    def reject():
        raise RuntimeError("Other integrity guard failed")
    with connection(owner) as raw:
        with pytest.raises((psycopg.errors.UndefinedTable, RuntimeError)):
            guarded_apply(raw, change="ALTER TABLE public.absent_guard_table ADD COLUMN x integer" if failure == "sql" else None,
                          precommit=reject if failure != "sql" else None)
        assert raw.info.transaction_status == TransactionStatus.IDLE
    assert fingerprints(owner) == rows_before and metadata(owner) == metadata_before


def empty_snapshot():
    return {"format": SNAPSHOT_FORMAT, "render_search_path": RENDER_SEARCH_PATH,
            "schema": {key: [] for key in SCHEMA_QUERIES}}


@pytest.mark.parametrize("corruption", ["legacy", "wrong_path", "missing_category", "wrong_format"])
def test_old_or_incomplete_snapshots_cannot_authorize_commit(corruption):
    first, other = empty_snapshot(), empty_snapshot()
    if corruption == "legacy":
        other = other["schema"]
    elif corruption == "wrong_path":
        other["render_search_path"] = "public"
    elif corruption == "missing_category":
        del other["schema"]["columns"]
    else:
        other["format"] = "unreviewed"
    with pytest.raises(InvalidSchemaSnapshot):
        require_unchanged_application_schema(first, other)


def test_qualified_identifiers_and_literal_values_are_not_stripped():
    first = empty_snapshot()
    first["schema"]["columns"] = [{"default_expression": "'public.literal'::text"}]
    other = deepcopy(first)
    other["schema"]["columns"][0]["default_expression"] = "'literal'::text"
    with pytest.raises(SchemaMismatch, match="columns"):
        require_unchanged_application_schema(first, other)


def test_optimized_python_cannot_disable_guard():
    root = Path(__file__).resolve().parents[1]
    program = """
from scripts.lead_security_guard import *
before={'format':SNAPSHOT_FORMAT,'render_search_path':RENDER_SEARCH_PATH,'schema':{k:[] for k in SCHEMA_QUERIES}}
after={**before,'schema':{**before['schema'],'columns':[{'unexpected':'change'}]}}
try:
    require_unchanged_application_schema(before,after)
except SchemaMismatch:
    raise SystemExit(0)
raise SystemExit(1)
"""
    result = subprocess.run([sys.executable, "-O", "-c", program], cwd=root, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_snapshots_round_trip_json_without_losing_validation_metadata():
    before = empty_snapshot()
    require_unchanged_application_schema(before, json.loads(json.dumps(before)))
