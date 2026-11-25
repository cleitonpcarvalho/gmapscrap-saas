"""Canonical structural-schema guard for the reviewed lead-security runner.

This module never opens connections, loads application settings, or commits.
The caller owns the transaction and must roll it back on any guard exception.
RLS/ACL/default-privilege changes have separate security checks in the runner;
they are intentionally not part of this structural snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping

from psycopg.pq import TransactionStatus


SNAPSHOT_FORMAT = "gmapscrap-public-schema-v1"
RENDER_SEARCH_PATH = "pg_catalog"

# Keep the actual definitions, including literal strings and qualified names.
# Removing "public." or normalizing SQL text could hide real schema changes.
SCHEMA_QUERIES = {
    "tables": """
        SELECT c.relname AS table_name, c.relkind, c.relpersistence,
               c.relispartition, pg_get_userbyid(c.relowner) AS owner
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        ORDER BY c.relname
    """,
    "columns": """
        SELECT c.relname AS table_name, a.attnum, a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull AS not_null,
               pg_get_expr(d.adbin, d.adrelid) AS default_expression,
               a.attidentity, a.attgenerated,
               CASE WHEN a.attcollation = 0 THEN NULL
                    ELSE a.attcollation::regcollation::text END AS collation
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
    """,
    "constraints": """
        SELECT c.relname AS table_name, k.conname, k.contype, k.convalidated,
               pg_get_constraintdef(k.oid) AS definition
        FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
        ORDER BY c.relname, k.conname
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY tablename, indexname
    """,
    "policies": """
        SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """,
    "triggers": """
        SELECT c.relname AS table_name, t.tgname, t.tgenabled,
               pg_get_triggerdef(t.oid) AS definition
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND NOT t.tgisinternal
        ORDER BY c.relname, t.tgname
    """,
    "routines": """
        SELECT p.oid::regprocedure::text AS signature,
               pg_get_userbyid(p.proowner) AS owner,
               pg_get_functiondef(p.oid) AS definition
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p', 'w')
        ORDER BY p.oid::regprocedure::text
    """,
    "views": """
        SELECT c.relname AS view_name, c.reloptions,
               pg_get_viewdef(c.oid) AS definition
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')
        ORDER BY c.relname
    """,
    "sequences": """
        SELECT c.relname AS sequence_name,
               format_type(s.seqtypid, NULL) AS data_type,
               s.seqstart, s.seqincrement, s.seqmin, s.seqmax,
               s.seqcache, s.seqcycle
        FROM pg_sequence s JOIN pg_class c ON c.oid = s.seqrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' ORDER BY c.relname
    """,
}


class InvalidSchemaSnapshot(ValueError):
    """An old, incomplete or noncanonical snapshot cannot authorize a commit."""


class SchemaMismatch(RuntimeError):
    def __init__(self, categories: list[str]):
        self.categories = tuple(categories)
        super().__init__("Application schema changed outside security; rollback: "
                         + ", ".join(categories))


def capture_application_schema(connection) -> dict:
    """Render all definitions identically inside an existing transaction.

    SET LOCAL limits the setting to the caller's transaction. Restore its exact
    previous value after a successful snapshot, even if it is a custom path.
    On a database error leave the aborted transaction to the caller to roll back.
    No substring replacement or search_path-sensitive preflight output is reused.
    """
    if connection.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("Schema capture requires an active transaction")
    previous = connection.execute("SELECT pg_catalog.current_setting('search_path')").fetchone()[0]
    try:
        connection.execute("SELECT pg_catalog.set_config('search_path', %s, true)", (RENDER_SEARCH_PATH,))
        schema = {}
        for category, statement in SCHEMA_QUERIES.items():
            cursor = connection.execute(statement)
            names = [column.name for column in cursor.description]
            schema[category] = [dict(zip(names, row)) for row in cursor.fetchall()]
        return {"format": SNAPSHOT_FORMAT, "render_search_path": RENDER_SEARCH_PATH, "schema": schema}
    finally:
        if connection.info.transaction_status == TransactionStatus.INTRANS:
            connection.execute("SELECT pg_catalog.set_config('search_path', %s, true)", (previous,))


def require_unchanged_application_schema(before: Mapping, after: Mapping) -> None:
    """Fail closed on genuine differences, missing sections or legacy snapshots.

    Raise an exception, rather than using assert, so Python -O cannot disable
    the pre-commit guard. The runner must COMMIT only after this returns.
    """
    for snapshot in (before, after):
        if (not isinstance(snapshot, Mapping)
                or snapshot.get("format") != SNAPSHOT_FORMAT
                or snapshot.get("render_search_path") != RENDER_SEARCH_PATH
                or not isinstance(snapshot.get("schema"), Mapping)
                or set(snapshot["schema"]) != set(SCHEMA_QUERIES)
                or any(not isinstance(rows, list) for rows in snapshot["schema"].values())):
            raise InvalidSchemaSnapshot("Capture both schemas with the canonical guard; do not reuse legacy snapshots")
    changed = [category for category in SCHEMA_QUERIES
               if before["schema"][category] != after["schema"][category]]
    if changed:
        raise SchemaMismatch(changed)
