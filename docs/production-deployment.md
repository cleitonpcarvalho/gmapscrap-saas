# Production deployment gate

On November 25, 2026 deployment was initially blocked for ownership review of
paused searches **29, 38 and 40**. The user subsequently authorized resuming the
release while preserving these searches without restarting, reclassifying,
canceling, or changing their existing fields/statuses. Paused rows are excluded
from startup's resume selector; the migration/startup guards now match its
`queued`/`running` states. No source ownership is inferred or recorded for paused
rows. Original row fingerprints and paused statuses must match after deployment.

The unchanged production release is `0a4e4826e40f1b2261849e7979b656b349c4fa77`.
Both running image configuration IDs occur in the build logs of its
[successful deployment run](https://github.com/cleitonpcarvalho/gmapscrap-saas/actions/runs/45405760448):

- Backend: `sha256:c6ef4e6f0acfd0df211e2590d6c5f47597c245164235a7a1b4553873f457e86c`
- Frontend: `sha256:4d37fc2d0f529612fc4c62ed081c9748bed7d67e07d0deec5cc2a19b4ccac8ed`

Read-only production preflight confirmed PostgreSQL 17.6, effective role
`postgres`, both pending feature migrations absent, 786 leads, 16 niches, 42
searches, 42 CRM cards, 109 activities and one follow-up. Backend health and
frontend `/` and `/crm` returned HTTP 200; anonymous CRM access returned 401.
These are audit-time observations, not a freeze of normal application activity.

## Workflow

`.github/workflows/docker-images.yml` retains deployment on pushes to main.
Branch pushes and pull requests run tests; branch pushes also build release
images, but do not access the production database or update services. A single
non-canceling GitHub Actions concurrency group and a VPS file lock serialize
preparation and deployment.

The test job uses disposable PostgreSQL 17 services on loopback ports 55488 and
55489, separate test administrators, the locked Python dependencies, and the Qt
desktop runtime. It runs backend, PostgreSQL, CRM drag-and-drop, desktop, frontend
and TypeScript checks. Production images are built only after tests pass. The
frontend image build also checks the production Next.js build.

After safety checks and authorization to resume, push the release branch and
wait for tests/builds to pass. Before merging, dispatch this workflow on that
exact branch with `mode=prepare`. **Preparation changes production schema** after
its backup and rehearsal pass; it does not update either service. If specific
legacy searches are positively verified as server searches, supply only those
IDs through `verified_server_search_ids`. This input does not classify desktop
searches or alter existing search statuses. Confirmed historical desktop searches
need a separate reviewed resolution; the gate does not rewrite them.

Merge only after preparation succeeds and no source changes have invalidated the
checks. The main push runs the same test/build/backup/migration gate again before
deployment. All three images are checked for the release revision and resolved
to registry digests before migration. Swarm receives the full commit tag plus
digest, rather than `latest`. A manual `mode=deploy` dispatch is permitted only on
main. Mutable `latest` tags are not promoted by this workflow; do not redeploy the
old stack definition expecting it to select the current release automatically.

## Credentials and backup

`scripts/production_release.py` resolves database configuration inside the live
`gmapscrap_backend` container, using its exact `DB_*` / `DATABASE_URL` precedence.
It passes existing PG connection values through inherited process environment
variables. There are no new production credentials, secret-bearing arguments,
environment files, or database dumps in the repository or Actions artifacts.
The existing `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, and registry authentication are
reused. Database connections must target the backend's Supabase host, require TLS,
and use the effective `postgres` owner on PostgreSQL 17. Version/role drift stops
the gate rather than silently switching targets or credentials.

`Dockerfile.migrations` supplies matching PostgreSQL 17 backup/restore binaries
and the locked application dependencies. The non-root helper creates a complete
custom-format database archive from an exported repeatable-read snapshot. Before
any production DDL it:

1. Reads the archive TOC and decompresses the entire archive without printing SQL.
2. Computes its SHA-256 checksum.
3. Restores the **public application schema**, with original object owners/ACLs,
   to a new PostgreSQL cluster inside that helper's private temporary filesystem.
4. Compares all existing public-table rows with the exported production snapshot.
5. Rehearses the pending migrations and validates the matching backend's model
   columns and authenticated read endpoints against that restored database.
6. Checks the archive checksum again before production migration.

This is an application-schema restore rehearsal, **not** a full Supabase managed
service recovery or a restore of provider-owned schemas. The full archive is
retained; restoration of Auth, Storage objects, managed extensions and external
services requires the provider's recovery procedure. Unsupported restore
dependencies fail closed. No production restore or destructive rollback occurs.

Backups and sanitized evidence stay under private directories in
`/var/lib/gmapscrap-deploy/<commit>-<unique-id>/` on the VPS. The parent and backup
directories are mode 0700; archives and evidence are mode 0600. Do not upload these
archives to Actions or commit them. There is no automatic deletion or pruning.

## Migration and preservation checks

The helper can execute only:

- `migrations/20261124_crm_company_profiles.sql`
- `migrations/20261124_desktop_execution.sql`

Historical CRM, niche and lead-security SQL is never loaded or executed by the
production helper. Existing prerequisite schema and RLS/ACL state are inspected
read-only. Unknown ownership, policies, inheritance, exposed API table/column/
sequence privileges, partial installation, missing prerequisites, or changed
checksums stop the release. Exact existing installations are adopted after
validation without reapplying their SQL.

Both pending bodies and their private RLS-protected migration-ledger entries
commit in one production transaction, with advisory locking and bounded lock/
statement timeouts. Their original top-level BEGIN/COMMIT wrappers are removed
only within this enclosing transaction; the checked-in SQL files are unchanged.
Existing public tables are briefly SHARE-locked while every original row value,
table/column ACL, default ACL, and sequence counter is compared before/after.
Only the new company-profile table, the two search columns/index, and the release
ledger may be added. No lead backfill, lead rewrite, status rewrite, old-security
reapplication, or global privilege change is performed.

Verified server IDs are retained as review metadata in the desktop ledger entry.
While the legacy backend is still running, any additional queued/running
server-default search without verified ownership blocks deployment, even after
preparation. Paused searches remain unchanged and are never submitted by startup.

## Deployment and verification

After the gate passes, only `gmapscrap_backend` and `gmapscrap_frontend` may be
updated. The existing single-replica topology is required. Rollouts use stop-first
ordering to avoid concurrent legacy/new schedulers. Failure pauses the release;
there is no automatic rollback, stack redeploy, volume operation, database restore,
or update to unrelated services.

The backend receives `GMAPSCRAP_SCHEMA_MANAGED=1`: startup validates all model
columns read-only and fails if incompatible. On the first managed startup it
also rechecks legacy active-search ownership before starting schedulers, closing
the interval between migration commit and stopping the old process. It records
completion only in the private release ledger; search/lead rows are unchanged.
Later restarts accept correctly classified work from the updated backend.
Startup does not run legacy DDL or backfills. Development startup behavior is unchanged. The health
response includes `GMAPSCRAP_RELEASE_SHA` for managed releases.

Before proceeding from backend to frontend, the workflow checks backend health
and the exact release SHA. Final verification checks Swarm rollout state, running
image IDs/revision labels/digest references, public frontend `/` and `/crm`, login,
authenticated CRM pipelines/cards/leads/follow-ups, niches and searches, and
anonymous CRM rejection. Only status codes, counts, hashes and release metadata
are logged. Smoke tests perform no lead/CRM/search writes. Detailed sanitized
evidence is retained beside the backup.

The local regressions additionally exercise atomic failure of the second
migration, no reapplication on retry, checksum/partial-schema drift, active-search
ownership refusal, archive restore and API compatibility, read-only managed
startup, and refusal to update any service when the migration gate fails.

## Local validation on November 25, 2026

- Complete backend/security/PostgreSQL suite: 373 passed, three optional checks
  skipped. Final focused release-gate suite after the handoff changes: 11 passed.
- The skipped real Chrome cancellation check was run separately and passed.
  Packaged macOS app and standalone PostgREST checks were not run.
- Frontend: 53 tests passed; TypeScript and production Next.js build passed.
- GitHub Actions `actionlint`, Python compilation, and `git diff --check` passed.
- Local Docker was unavailable. The new migration image and changed workflow
  have not been executed in GitHub Actions or production. Those checks and a
  fresh production backup/restore rehearsal must pass before deployment resumes.
