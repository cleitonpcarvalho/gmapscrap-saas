# Lead database security migration

`migrations/20261124_lead_security.sql` is an explicit PostgreSQL 17+ security
migration. It has not been applied to production. Application code, production
configuration and all existing desktop/CRM work remain unchanged.

## Scope and expected behavior

- Enable RLS without FORCE RLS or allow-all policies on `public.leads`,
  `search_runs`, `lead_tags` and `tags`.
- Revoke every table privilege, including TRUNCATE and PG17 MAINTAIN, and every
  independent column privilege from PUBLIC, anon and authenticated.
- Discover owned sequences through catalog dependencies, including renamed
  sequences, and revoke their SELECT/USAGE/UPDATE grants from the same roles.
  The existing owned ID sequences for leads, searches and tags must be present.
- Preserve postgres/service_role grants and role attributes. Verify each trusted
  table privilege and sequence privilege separately before committing; missing
  privileges abort rather than silently broadening trusted access.
- Remove API/PUBLIC defaults for **future postgres-created public tables and
  sequences**. Existing unrelated table grants, function defaults, other schemas
  and defaults belonging to other creators are unchanged.

The FastAPI backend connects as effective role postgres and uses its own session
cookie authentication. Scraping, search lifecycle updates, CRM, company editing,
tag operations and backups use that backend connection. The frontend and desktop
call FastAPI; they do not need direct anon/authenticated table access.
service_role retains its existing BYPASSRLS attribute and direct grants.

The migration contains no business INSERT/UPDATE/DELETE/TRUNCATE, sequence value
changes, backfills, table/column creation, FK changes, role changes or CASCADE.
It does not install the pending company-profile or desktop migrations.

## Transaction and failure behavior

The whole migration runs in one explicit transaction, with a fixed pg_catalog
search path, a nonblocking advisory lock, a 5-second lock timeout and a 30-second
statement timeout. It requires the existing effective postgres owner.

All four table locks are acquired with ACCESS EXCLUSIVE **NOWAIT**. An active
scraping/CRM transaction can therefore make the migration fail immediately with
SQLSTATE 55P03. Retry during a quiet window; do not remove NOWAIT to force it
through. Other catalog lock waits are bounded by the lock timeout.

The migration also aborts, preserving the original state, for:

- Missing tables/roles/owned ID sequences; changed ownership; partitioning,
  inheritance, existing policies or unexpected FORCE RLS.
- Unsafe API role attributes, the ability to SET ROLE to postgres/service_role,
  public-schema CREATE access, or a service_role without expected BYPASSRLS.
- API-accessible dependent views/materialized views, including transitive views,
  or public browser-executable SECURITY DEFINER routines. These are reviewed
  rather than rewritten or silently stripped of privileges.
- Global postgres table/sequence default grants that a schema-local REVOKE cannot
  override, or effective API privileges remaining through role inheritance.
- Loss of any expected postgres/service_role table or sequence permission.

With a stop-on-error SQL client, any error rolls back the whole transaction.
An application restart is unnecessary. Repeated successful execution produces
the same permissions/defaults and does not modify business rows or counters.

## Default privileges and remaining scope

The audited application creates its objects as postgres, so the migration closes
that creator's future public table/sequence exposure while preserving its
service_role defaults. Global defaults cannot be negated by per-schema REVOKE;
unexpected global API defaults cause a fail-safe rollback.

Supabase also has provider-owned `supabase_admin` defaults granting API access.
Those remain unchanged, and the migration emits a NOTICE naming such creators.
Objects created as supabase_admin or another owner still need explicit security
and a separate provider-authorized default-privilege review. Do not claim every
possible future creator is covered by the application-owner defaults.

Future views, explicit GRANT statements and SECURITY DEFINER RPC functions also
require review. In particular, function EXECUTE defaults are outside this focused
table/sequence migration. The migration checks currently exposed definer RPCs;
it cannot prevent a privileged administrator from adding a bypass afterward.
Existing unrelated application tables are outside this four-table change.

## Local regression tests

`tests/test_postgres_lead_security.py` accepts only a disposable PostgreSQL
security_admin cluster on localhost/127.0.0.1 port **55489**, database `postgres`,
without connection-string override parameters. Every test creates and drops its
own synthetic database. The server should be dedicated to these tests.

Set `GMAPSCRAP_TEST_LEAD_SECURITY_URL` to that isolated connection. Override
DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_SSLMODE to empty and DATABASE_URL to
`sqlite://` before importing the application in tests. Set a local-only session
secret. Do not supply production credentials to the test process.

The optional `GMAPSCRAP_TEST_POSTGREST_BIN` points to a temporary official
PostgREST binary. The HTTP test binds only 127.0.0.1:55490 and creates local test
JWTs; it uses no Supabase project keys or Auth users. A macOS binary may need
DYLD_LIBRARY_PATH pointing to the existing PostgreSQL libpq directory.

Tests cover complete row fingerprints, history/CRM notes/activities/follow-ups/
values/tags, unchanged constraints/indexes/counters, repeatability, column grants,
sequence grants, inheritance/global-default failures, busy locks, wrong roles,
view/RPC guards, future table defaults and accidental table regrants with RLS.
Backend/API regressions cover real ORM scrape persistence and duplicate handling,
CRM filters/bulk selection, company overrides preserving run provenance, and
Pause/Resume/terminal Stop status writes. No Selenium/provider calls are made.

The pending company migration is tested only if that optional feature is present;
the security SQL itself has no dependency on it. Local model fixtures may include
pending desktop fields; that does not imply those fields are installed in production.

Actual HTTP checks first confirm the insecure baseline, apply the migration twice,
then test GET/POST/PATCH/DELETE for unauthenticated requests and valid local anon/
authenticated JWTs on all four tables. All 48 attempts must fail with permission
errors and unchanged row fingerprints; trusted service-role reads must succeed.
This verifies database/PostgREST authorization, not Supabase's hosted key gateway.

### Validation recorded on November 24, 2026

- Final selected backend suite: **103 passed, 9 skipped**. All **24 new migration
  tests passed**, including the real HTTP test. The nine skips are existing desktop
  PostgreSQL variants restricted to the separate port-55488 fixture; their SQLite
  variants ran. Existing FastAPI/Starlette deprecation warnings remain.
- PostgreSQL 17.11 plus SHA-256-verified official PostgREST 16.6: all 48 anonymous/
  anon/authenticated HTTP GET/POST/PATCH/DELETE attempts denied with 42501; four
  service_role reads succeeded. No hosted Supabase requests were made.
- Separate network-disabled PostgreSQL **17.6** restore of the verified production
  backup: **174 checks passed** for the exact final migration, including repeated
  application. All **69 table row fingerprints** remained identical and all
  **28 archived sequence states** matched after rollback-only fixture tests.
- The restored copy changed only RLS/ACLs on the four target tables, ACLs on their
  three sequences, and postgres public table/sequence defaults. Provider defaults
  and unrelated objects remained unchanged. The source backup was mounted read-only.
- Complete selected regression coverage includes CRM/company editing, import
  eligibility, tags, scraping persistence/duplicates, history and search lifecycle.
- Migration SHA-256:
  `d2206a8ca2cf1f25411bef0dd23c6ec4637f7366e0fe2fda4500126a4881ceef`.

## Pre-commit schema guard correction

The November 24 production attempt was rolled back before COMMIT. The reviewed
SQL and its security checks succeeded, but the external runner's comparison
`all(v == pre['application_schema'][k] for k, v in schema.items())` compared
preflight definitions from the normal search path with definitions rendered
under the migration's `SET LOCAL search_path = pg_catalog`.

PostgreSQL consequently rendered the same default as
`nextval('crm_funnel_stages_id_seq'::regclass)` versus
`nextval('public.crm_funnel_stages_id_seq'::regclass)`. Foreign-key targets and
trigger function names had the same qualification difference. No business or
structural schema change caused that failure; all transaction changes rolled back.

[`scripts/lead_security_guard.py`](../scripts/lead_security_guard.py) captures
every schema snapshot inside an existing transaction using the same **pg_catalog**
search path, and restores the caller's exact previous path with transaction-local
`set_config`. It never opens connections, imports app settings, commits, or changes
business records. No SQL substrings or literal values are stripped or rewritten.

Both preflight and pre-commit snapshots must use this module. A snapshot records
its format and rendering path; legacy, incomplete or incompatible snapshots fail
closed. Compare preflight with a fresh snapshot after acquiring the transaction
locks, then compare again after the reviewed DO block and before COMMIT:

```python
# Existing read-only preflight transaction:
preflight_schema = capture_application_schema(connection)

# Later, inside the reviewed migration transaction, after NOWAIT locks:
before_schema = capture_application_schema(connection)
require_unchanged_application_schema(preflight_schema, before_schema)
# Execute the exact reviewed security DO block; keep every other existing guard.
require_unchanged_application_schema(
    before_schema, capture_application_schema(connection)
)
# COMMIT only after all schema, row, sequence, role and security checks pass.
# On any exception, the runner must ROLLBACK and stop.
```

The guard compares exact canonical table/view inventories, column types/defaults/
nullability/collations, constraints, indexes, policies, triggers, routine and view
definitions, and sequence definitions. It raises exceptions rather than using
`assert`, so Python optimization cannot disable it. Genuine schema differences,
including definitions containing the literal text `public.`, remain detectable.

RLS/ACLs and creator default privileges are checked separately by the unchanged
security/integrity guards, because this migration intentionally changes them.
All-table row fingerprints, sequence last_value/is_called states, unrelated
metadata, trusted grants, roles, memberships, and the exact migration SHA-256
must still pass. This correction does not relax any migration SQL checks or change
the reviewed migration file.

The prior failed runner and reports are retained unchanged outside Git. A corrected
copy is prepared at
`/private/tmp/gmapscrap-security-guard-20261124T205919Z/gmapscrap-apply-security-corrected.py`,
with a reviewable `runner-correction.diff` beside it. Its preflight captures the
canonical snapshot; its transaction compares the preflight, pre-DO and post-DO
snapshots. It uses a fresh audit directory and rejects the previous legacy snapshots.
No production mode of this corrected runner has been executed.

Regression tests are in
[`tests/test_lead_security_guard.py`](../tests/test_lead_security_guard.py).
Use the same disposable localhost:55489 fixture and SQLite application overrides
described above. They reproduce the exact old false-positive categories, exercise
real schema-change rollbacks, verify stale-preflight rejection and repeatability,
and check that transaction boundaries and the caller's search path are preserved.

### Guard validation on November 24, 2026

- **53 passed, no skips** on PostgreSQL **17.6**: 29 guard regressions and the
  existing 24 migration/backend/REST tests. The real PostgREST test again denied
  all 48 browser CRUD requests and allowed four service_role reads, locally only.
- A fresh complete restore of the November 24 backup reproduced all three old
  mismatch categories (columns, constraints, triggers). The canonical comparison
  accepted those unchanged definitions.
- On that restore, **13 genuine schema mutations** triggered full rollback,
  including column/type/nullability/default, constraint, index, trigger, policy,
  table, view, routine and sequence-definition changes. Data, security metadata,
  defaults and original structure were checked again after each rollback.
- The exact reviewed migration committed **twice in the isolated restore** with
  identical structural snapshots, all **69 table fingerprints** unchanged and
  all **28 sequence states** unchanged. Only the expected seven relation ACL/RLS
  objects and postgres table/sequence defaults changed. Provider defaults stayed
  unchanged. The backup and migration SHA-256 hashes matched before/after.
- Test evidence, corrected runner and its diff:
  `/private/tmp/gmapscrap-security-guard-20261124T205919Z/`.
  The cluster used temporary storage, a dedicated Docker network and a database
  port bound only to 127.0.0.1; its backup mount was read-only. No production
  connection, production migration, application deployment or configuration change
  was made. Existing FastAPI/Starlette deprecation warnings remain.

The corrected guard is ready for a newly authorized production attempt using
**fresh canonical preflight snapshots** and backup/schema checks. Do not reuse
the old preflight JSON. The prior production rollback and its audit records remain
untouched. The previously reported hosted authenticated-JWT probe limitation
still requires an existing token; do not create production Auth users just to test.

## Production procedure — previous attempt rolled back

1. Recheck effective backend role, provider/creator defaults, policies, dependent
   views/RPCs and trusted grants. Verify a fresh recoverable backup and capture
   current ACL/default definitions. The tested backup is a point-in-time snapshot;
   production has remained active since it was created.
2. Isolate the security migration and its tests/docs from pending desktop/CRM code.
   Do not deploy the dirty backend tree: its pending startup logic would add
   execution_source/desktop_request_id columns independently of this migration.
3. In a later authorized maintenance step, use the existing secure postgres
   connection and a client with ON_ERROR_STOP. Run only this reviewed migration.
   On 55P03, leave the rolled-back state intact and retry during a quiet window.
4. Verify RLS/ACLs/defaults and each trusted permission. Check hosted Supabase REST
   with anon/publishable keys and an existing authenticated token: no table reads
   or writes should succeed. Do not create production Auth users just for a probe.
   Verify backend leads/searches/tags/CRM reads through the authenticated API.
5. After those checks, the separately reviewed company-profile migration is
   compatible and can be considered for its own authorized application/release.
   It stores commercial classification separately from historical scraping runs.

Production REST remains exposed until the migration is actually applied. The local
HTTP results cannot be presented as post-migration production verification.
Unexpected external consumers using anon/authenticated will intentionally lose
access; no such application dependency was found. Secret/service-role credentials
must remain server-side. Reversing security after COMMIT needs a separate reviewed
plan; do not restore broad API grants as an automatic rollback.

References: [PostgreSQL defaults](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html),
[RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
[Supabase Data API security](https://supabase.com/docs/guides/api/securing-your-api).
