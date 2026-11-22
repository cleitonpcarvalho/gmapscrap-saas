# Existing CRM security migration

`migrations/20261121_crm_security.sql` was applied and verified in production on
2026-11-22, before the separately authorized Phase 1 migration. It changes
authorization only. Do not rerun it during application deployment. The reviewed
migration files and Docker/Traefik configuration are unchanged. Separate application
fixes for populated pipeline/stage deletion are documented in
[`crm-transfer-fixes.md`](crm-transfer-fixes.md).

## Scope and behavior

- Enables RLS on `crm_leads`, `crm_funnels`, `crm_funnel_stages` and
  `crm_stage_history`, without FORCE RLS or permissive browser policies.
- Revokes all table and independent column privileges from PUBLIC, anon and
  authenticated. Table-level REVOKE alone would leave independent column grants.
- Discovers owned serial/identity sequences through catalog dependencies,
  including renamed sequences, and revokes browser/PUBLIC sequence privileges.
  Sequence ownership, current values and `is_called` are unchanged.
- Preserves ownership and explicitly retains postgres table, sequence and routine
  access. The production backend uses effective role postgres; table-owner access
  works even without SUPERUSER or BYPASSRLS, as demonstrated in tests.
- Restricts related routine execution using table/sequence/type dependencies,
  attached trigger functions, explicit CRM table references in public routine
  source, and catalog-tracked callers. Existing bodies, triggers, search paths,
  SECURITY DEFINER flags and business behavior are not rewritten.
- Also revokes browser/PUBLIC EXECUTE on the optional
  `gmapscrap_crm_activity_immutable()` helper if that future Phase 1 function is
  already present. No new activity/follow-up tables are created by this migration.
- Leaves unrelated tables, service_role grants, role memberships, default
  privileges, all constraints/indexes, rows, notes, timestamps and relationships
  unchanged. No global REVOKE, ALTER DEFAULT PRIVILEGES, ownership changes,
  backfills, DROP operations or CASCADE revocations are used.

The script requires the effective postgres owner and all four expected ordinary
postgres-owned tables with owned ID sequences. It aborts for inheritance,
pre-existing RLS policies, exposed dependent views, extension-owned related
routines, unclassified browser-executable public SECURITY DEFINER routines, or
effective API privileges remaining through inherited roles. Unexpected objects
require review rather than being silently rewritten outside scope. All changes
roll back on failure.

RLS does not replace application authentication. Browser roles lose direct CRM
access; the trusted backend continues to use its existing signed single-login
session and owner connection. Direct Supabase browser access to these tables is
intentionally unsupported.

## Isolated validation on 2026-11-21

The complete backend/API/desktop/PostgreSQL suite passed: **240 tests**, no skips,
with four existing deprecation warnings. This includes **15 PostgreSQL security
cases** in `tests/test_postgres_crm_security.py` and **18 PostgreSQL transfer
regressions** in `tests/test_postgres_crm_transfers.py`. All **15 frontend tests**
also passed.

Each security fixture accepts only explicitly configured loopback PostgreSQL port
55488, creates a unique `gmapscrap_crm_security_test_*` database, uses synthetic
data, and drops that database afterward. The backend test role is postgres with
neither SUPERUSER nor BYPASSRLS. No production reads or writes were needed for
this implementation.

Coverage includes:

- Two consecutive security applications with identical full application row
  snapshots, columns/defaults, constraints, indexes, policy metadata, default
  ACLs, and every sequence counter. Fixtures include nine cards, four historical
  notes, seven stage changes, leads, searches and tags.
- Actual denied reads, inserts, updates, deletes, truncates, nextval and setval
  under both browser roles, independent column ACL removal, PUBLIC ACL removal,
  and deny-by-default RLS after an accidental table grant.
- Related definer RPCs, SQL wrappers, PL/pgSQL references and trigger functions;
  unrelated routine privileges and function bodies remain intact.
- Renamed sequence discovery; fail-closed rollback for inherited access,
  unexpected execution role, existing policies, exposed views and untracked
  definer RPCs.
- All 11 existing CRM route handlers exercised through authenticated HTTP using
  both the deployed release `fa3871aa43fc38988112c8eafbd63b84ffb69b85` and the
  pending working tree, before and after hardening. Deployed source is extracted
  from local Git into an isolated temporary directory; no checkout is changed.
- Pipeline/stage reads, creation, editing, reordering, card membership, duplicate
  prevention, multiple pipelines, note persistence, stage movement, empty
  deletion, protected/conflicting deletion and trusted backend AI updates.
- Security before/after Phase 1, repeated hardening, manual card creation,
  append-only notes, follow-up creation/completion, explicit won outcomes and
  database rejection of activity edits.

## Application failures and separate fixes

Two populated-delete paths in the archived deployed release fail both before and
after security:

1. Delete a populated stage while moving its cards: SQLAlchemy's loaded
   relationship tries to set `crm_leads.stage_id` to NULL (SQLSTATE 23502).
2. Delete a populated pipeline while moving its cards: the analogous relationship
   tries to set `crm_leads.funnel_id` to NULL (SQLSTATE 23502).

Both legacy transactions roll back and preserve the card and notes. The probe
verifies that preservation and records these failures only for the archived
release. The current working tree fixes both paths through the separate atomic
relationship-transfer service; the same authenticated HTTP probe now requires
successful populated deletion before and after hardening. Additional PostgreSQL
tests exercise manual CRM, unchanged notes/follow-ups/outcomes, duplicate
membership rejection, rollback after a flushed transfer, and concurrent inserts.
The security migration itself is unchanged; these were application bugs, not
permission/RLS regressions. Production has not received these application fixes.

## Production application and future installation precautions

The production execution used the restore-tested November 21 full backup.
Security was applied first; Phase 1 was then applied transactionally with an
explicit `REVOKE ALL ON FUNCTION public.gmapscrap_crm_activity_immutable()
FROM anon, authenticated`. Both changes preserved existing rows, notes, sequence
values and backend access. All six CRM tables now have RLS enabled and browser
roles lack direct access. The following ordering is retained for a future fresh
installation or separately approved recovery; it is not a deployment runbook.

1. Obtain a current recoverable full backup and validate an isolated restore.
   The previously audited November 19 archive is intact but predates current CRM
   state and all 16 niches; this task did not create a replacement backup.
2. Revalidate current ownership, dependent views/functions, policies and role
   memberships. The last read-only audit found the expected four tables, no CRM
   triggers, and broad browser grants with RLS disabled. Catalog drift must be
   reviewed rather than bypassing the script's safeguards.
3. Apply this security migration only after explicit production authorization,
   using the existing effective postgres connection and stop-on-error execution.
   Its transaction, advisory lock, 10-second lock timeout and 60-second statement
   timeout must remain. ACCESS EXCLUSIVE locks can briefly block CRM requests;
   use a quiet window and verify grants/RLS and backend operations afterward.
4. Apply security before the separately authorized manual CRM migration so new
   commercial columns never inherit the old browser exposure. The pending
   manual migration currently creates its trigger function with explicit browser
   EXECUTE defaults. Reapply this repeatable security migration immediately
   afterward (tested), or separately review an explicit function-ACL fix to that
   pending migration. Production used the explicit function revoke, without
   rerunning the security migration. Do not assume a prior security pass affects
   future objects.

No deployment is needed for this authorization-only migration. Ordinary backend
CRM workflows retain their existing owner access. It does not disable AI or fix
the legacy stage-reset behavior; those application changes belong to Phase 1.

## Remaining boundaries and rollback

Other application tables and Supabase-wide defaults are outside this scope and
need their own security review. service_role and the backend owner remain highly
trusted. Catalog and source-reference discovery cannot prove arbitrary dynamic
SQL or private-schema RPCs safe; review new RPCs and views before exposure.

Before commit, PostgreSQL rolls back the authorization changes on error. After
commit, prefer retaining the security boundary. No automatic down migration is
provided: blindly restoring broad grants or disabling RLS would reopen the known
exposure. Any compatibility exception should use a separately reviewed narrow
grant/policy change, preserving owner access and all data.
