# Commercial CRM: bulk selection, company editing and representative

Implemented locally on November 24, 2026. No deployment, production queries,
production writes or production migrations were performed for this task.

## Behavior and API

- `Adicionar ao CRM` has **Selecionar todos** and **Desmarcar todos**. Selection
  survives pagination and filter changes. Selecting is read-only; only the
  explicit Add action creates memberships.
- Authenticated `GET /api/crm/manual/lead-selection` applies the exact same
  `q`, `niche`, `location` and ANY `tag_ids` filters as `/leads`, ordered by lead
  ID, and returns at most 1,000 IDs plus the total matching count. The UI unions
  these with prior selections and stops at 1,000. When the limit prevents a full
  selection it explains this. Existing selections outside the filter consume
  slots too. Existing memberships remain protected by the existing add API,
  funnel lock and `(lead_id, funnel_id)` unique constraint.
- **Editar empresa** in opportunity details uses the existing authenticated
  `PATCH /api/leads/{id}`. Only changed company fields are sent. Existing website
  normalization/duplicate checks and company email validation are reused.
- A nested `commercial_profile` object contains the opening `version` and any
  changed commercial classifications or representative fields. Version 0 means
  no profile existed. A Lead row lock serializes first inserts; profile versions
  reject stale edits with HTTP 409. Company edits through the legacy lead editor
  also invalidate commercial editor versions once the new table is installed.
- The original API's top-level niche/locality changes reassign `SearchRun`.
  The CRM editor therefore sends only `niche_override` and `location_override`
  inside `commercial_profile`. Mixing these safe edits with legacy top-level
  `niche`/`location` is rejected. CRM reads/filters use the override when present;
  `provenance` and the ordinary lead API continue to show the original run.
  Clearing an override restores the displayed source classification.
- Company name, main phone/email, site and address remain on the same Lead.
  Nothing creates a duplicate Lead or modifies opportunities, their versions,
  values/outcomes, tags, notes, activities, follow-ups or stage history.
- The single representative belongs to the company, shared across all its
  opportunities. Its `contact_name`, `contact_phone`, `contact_email` are separate
  from company contacts and CRM actors. Phone is normalized locally to E.164;
  contact email uses existing syntax validation without DNS. Direct `tel:`,
  `wa.me` and `mailto:` actions do not use Evolution or WhatsApp validation,
  perform no API mutation and do not claim delivery or append an activity.

## Migration and security

`migrations/20261124_crm_company_profiles.sql` creates only
`public.crm_company_profiles`, keyed by existing Lead ID. It adds no columns to
existing tables and performs no backfill or existing-row changes. It must be
applied explicitly as the existing effective `postgres` owner after manual CRM
phase 1. It has transaction, advisory lock and timeout protection and is
idempotent when the expected policy-free table is present.

The migration enables RLS, revokes table and independent column permissions
from PUBLIC/anon/authenticated and checks effective privileges. It aborts for
unexpected ownership, inheritance or policies instead of changing those rules.
It does not alter global/default grants, roles, existing CRM security,
Docker files, Supabase configuration or trusted service-role access.

Startup does not create this table. Without it, existing browsing, bulk
selection and CRM operations remain available. Company editing is visibly
disabled and direct profile writes return HTTP 503. A future release needs the
reviewed migration and both backend/frontend changes. The pending desktop
execution migration is independent and must not be bundled inadvertently.

## Changed files in this task

Modified:

- `backend/database.py`: exclude company profiles from implicit startup creation.
- `backend/main.py`: extend existing lead PATCH with safe, versioned company edits.
- `backend/manual_crm.py`: shared server filters, capped ID selection, profile reads.
- `backend/models.py`: company profile model only; existing desktop fields retained.
- `backend/schemas.py`: nested commercial edit input and safe-mode validation.
- `frontend/app/components/crm/AddToCrmDialog.tsx`: all-page selection controls.
- `frontend/app/components/crm/ManualCrmWorkspace.tsx`: editor and contact display/actions.
- `frontend/app/components/crm/types.ts`: commercial profile response type.
- `frontend/app/globals.css`: reset fieldset borders in existing CRM form grid.

Added:

- `backend/services/crm_companies.py`
- `frontend/app/components/crm/CompanyEditor.tsx`
- `migrations/20261124_crm_company_profiles.sql`
- `tests/test_crm_companies.py`
- `tests/test_postgres_crm_companies.py`
- `frontend/tests/crm-companies.test.tsx`
- `docs/crm-company-features.md`

No packages were added. Existing desktop source, worker/control modules,
dependency files and desktop migration match the task-start hash snapshot.
Shared backend files contain pre-existing desktop changes; a future release
must isolate the CRM hunks rather than stage those files wholesale.

## Validation

Final results on November 24, 2026:

| Check | Result |
| --- | --- |
| Relevant backend suite, including real local PostgreSQL | 112 passed |
| Complete frontend suite | 37 passed |
| `npx tsc --noEmit` | Passed |
| `NEXT_TELEMETRY_DISABLED=1 npm run build` | Passed, including `/crm` |
| Existing backend Docker production recipe | Passed locally |
| Existing frontend Docker production recipe | Passed locally with existing production API URL |
| Backend image import/OpenAPI/new CRM route smoke | Passed with networking disabled; startup/migrations not run |
| Frontend image `/crm` HTTP smoke | HTTP 200 with networking disabled |
| `git diff --check` | Passed |

The backend suite includes `test_crm`, `test_crm_funnels`, `test_manual_crm`,
`test_manual_crm_dnd`, `test_crm_companies`, `test_lead_read`, `test_tags`,
`test_email_validation`, `test_database_metadata`, `test_postgres_crm_companies`,
`test_postgres_crm_migration`, `test_postgres_crm_security`,
`test_postgres_crm_transfers`, `test_postgres_manual_crm` and
`test_postgres_manual_crm_dnd`. Existing FastAPI/Starlette deprecation warnings
remain; no test failures remain.

Local Docker images (native Linux ARM64; future production CI should rebuild
for the VPS architecture):

- `gmapscrap-backend:crm-companies-local-20261124`, built
  `2026-11-24T18:31:48Z` (15:31:48 America/Fortaleza), image
  `sha256:24f5e5b14e7ba2febdaa24001507324aab6564cfaeeceedc8bfcbfef8113779c`.
- `gmapscrap-frontend:crm-companies-local-20261124`, built
  `2026-11-24T18:31:42Z` (15:31:42 America/Fortaleza), image
  `sha256:af9cbe05c090d48a3483cbeeb7a9b8d33999b1bf7a187ce3f0cf258ab33fca0a`.

No images were pushed or deployed. The isolated local PostgreSQL cluster
started for these tests was stopped after the suite completed.

Frontend regressions cover all-page selection, filter parameters, retained
selections, explicit addition, the cap, deselection, loading/error handling,
safe company PATCH payloads, contact actions, version snapshots and migration
absence. Existing board drag-and-drop and manual CRM tests remain included.

Backend regressions cover the same filters/cap, duplicate memberships,
preservation of all commercial relationships and complete SearchRun snapshots,
company/contact validation, stale/atomic edits, clear-to-source overrides,
authentication, startup behavior and absence of external contact provider calls.

PostgreSQL checks use disposable synthetic databases restricted to localhost
port 55488. They verify persistence after reconnect, concurrent first edits,
idempotent migration, unchanged existing rows/default ACLs, existing CRM security,
RLS and denial of direct read/write access for browser roles.

Company email still uses the existing DNS-dependent validator when changed.
Representative actions open the user's dialer/browser/mail client; they do not
verify that a phone has a WhatsApp account. Local validation does not replace a
future authorized production smoke test.
