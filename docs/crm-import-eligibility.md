# CRM import eligibility and remembered pipeline

Implemented and validated locally on November 24, 2026. No deployment,
production data/configuration changes or database migrations were performed.
The existing bulk selection, commercial company editor, contact-person fields
and company-profile migration were extended or preserved rather than recreated.

## Import picker

- `Adicionar ao CRM` supplies the selected `funnel_id` to paginated lead reads
  and the existing all-page selection endpoint.
- The backend excludes memberships in that pipeline with a correlated SQL
  `NOT EXISTS` **before counting, ordering, offset and limit**. All existing
  memberships count, including legacy cards and won/lost opportunities.
  Membership in another pipeline does not exclude a company.
- Default results contain only available companies. `Mostrar já adicionados`
  includes existing memberships with `already_in_pipeline=true`; the picker
  labels them and disables their checkboxes. The available count is distinct
  from the displayed/paginated total when existing memberships are shown.
- The 25 matching / 10 imported example returns `matching_total=25`,
  `available_total=15`, `already_added_total=10`. Default `total=15`; with the
  toggle on, `total=25`. Pagination always uses the appropriate displayed total.
- `Selecionar todos` always uses eligible IDs, even with existing memberships
  visible. The previous 1,000 cap, retained selections across filters/pages,
  explicit Add action, duplicate reporting and backend duplicate protection
  remain in place. Selecting never creates a membership.
- Retained selections are revalidated against the new pipeline and existing
  companies before selection/import is enabled. This check is not limited by
  the visible page or current filters. Ineligible/deleted IDs are removed with
  feedback; eligible selections remain. Failed checks block import until retry.
- Pipeline changes reset pagination. Out-of-range pages after imports are reset
  safely. After adding, the available list/counts refresh. Responses from an old
  pipeline cannot replace the new pipeline's eligibility or selection state.

## API changes

- Existing authenticated `GET /api/crm/manual/leads` accepts optional
  `funnel_id` and `show_added=false`. It adds the counts and membership flag
  described above; unscoped callers retain their previous all-lead behavior.
- Existing `GET /api/crm/manual/lead-selection` accepts optional `funnel_id`;
  scoped selection always excludes that pipeline's memberships. Filtering still
  shares the existing company-name, commercial niche/locality and ANY-tag logic.
- New authenticated **read-only** `POST /api/crm/manual/lead-eligibility` accepts
  `{funnel_id, lead_ids}` (at most 1,000) and returns eligible retained IDs in
  their original order. POST avoids oversized URLs for retained selections; it
  does not insert/update/delete records or commit a transaction.
- Unknown pipelines return 404; invalid IDs/over-limit payloads return 422.
  Existing authentication, RLS, unique constraints and transactional Add API
  remain unchanged. No direct Supabase/browser database access is introduced.

## Pipeline preference

`usePipelineSelection` shares a single `gmapscrap.crm.pipelineId` localStorage
preference between the board and any import picker, including the picker opened
from the lead list. It synchronizes same-window components and storage events
from other tabs. Ordinary reloads/navigation/browser restarts restore that ID.

The initial UI displays a loading/validation placeholder until server metadata
validates the preference. Invalid/deleted IDs fall back to the first currently
available pipeline; an empty catalogue clears the preference and disables
import. The board does not fetch/display another pipeline as an interim choice.
Only freshly fetched metadata may persist a fallback. A sibling view whose
cached metadata does not recognize a new selection refreshes its catalogue,
preventing conflicting fallback loops after pipeline deletion/replacement.
Cards fetched for a prior pipeline stay hidden and cannot be dragged in the new
pipeline while its data is loading.

## Changed files in this task

- `backend/manual_crm.py`: pipeline eligibility, counts, membership flags and
  read-only retained-selection validation; existing Add/duplicate logic retained.
- `frontend/app/components/crm/AddToCrmDialog.tsx`: eligible picker, visibility
  toggle, pipeline-aware counts/bulk selection and retained-selection checks.
- `frontend/app/components/crm/ManualCrmWorkspace.tsx`: shared pipeline preference
  and protection against showing/moving cards from the preceding pipeline.
- `frontend/app/components/crm/types.ts`: optional membership flag.
- `frontend/app/components/crm/usePipelineSelection.ts`: new shared preference.
- `frontend/tests/crm-import-eligibility.test.tsx`: new eligibility/preference tests.
- `frontend/tests/crm-companies.test.tsx`: extend existing picker mocks/assertions
  for scoped counts and read-only eligibility; company/contact tests retained.
- `frontend/tests/manual-crm.test.tsx`: scoped picker fixtures and concurrent-import
  duplicate regression retained.
- `frontend/tests/setup.ts`: clear browser storage between tests.
- `tests/test_crm_import_eligibility.py`: new backend eligibility regressions.
- `docs/crm-import-eligibility.md`: this report.

## Validation and remaining limits

- Relevant backend suite: **100 passed**. Includes import eligibility, existing
  company/contact and provenance tests, manual CRM, drag-and-drop, funnels, lead
  reads, tags, email validation, metadata, WhatsApp AI and webhook regressions.
- Full frontend suite: **53 passed**, including the original company/contact,
  manual CRM and drag-and-drop tests. New coverage includes exact availability,
  pagination/filtering, selection counts, pipeline switching/pruning, retained
  IDs, stale responses, persistence/remount, synchronized views/tabs, deleted and
  replaced pipelines, empty catalogues, and blocked/quota-limited storage.
- TypeScript `npx tsc --noEmit`, Next.js production build and existing frontend
  and backend Docker production recipes passed locally. Docker builds use native
  Linux ARM64 and the existing production API build argument. Nothing is pushed.
- Backend image import/OpenAPI smoke runs with networking and startup disabled.
  No application startup migrations run during this check.
- Final frontend production image `/crm` smoke returned HTTP 200 with networking
  disabled. Local image tags are `gmapscrap-backend:crm-eligibility-local-20261124`
  and `gmapscrap-frontend:crm-eligibility-local-20261124`.
- Backend tests use disposable in-memory SQLite schemas, not migration scripts.
  PostgreSQL migration suites were deliberately not run for this request.
- Existing FastAPI/Starlette deprecation warnings remain; no test failures remain.

No new migration is required. The already-existing
`migrations/20261124_crm_company_profiles.sql` is unchanged and was not applied.
Company editing still needs that previously documented migration when deployed;
these import eligibility/preference changes add no schema requirements.

Availability is a read-time snapshot. Another user can import a company between
selection and Add; the existing funnel lock/unique constraint and skipped-ID
response prevent duplicate memberships. Browser storage restrictions can prevent
remembering a choice across restarts; selection still works in memory. A future
production release must include the backend/frontend API changes together and
rebuild for the VPS architecture, followed by an authorized smoke test.

The final preservation audit verified 159 pre-existing files byte-for-byte
unchanged, with 11 task-specific changed/added files listed above. Desktop Stop/Pause files,
shared backend models/schemas/main/database, company editing/contact service and
editor, migration files, dependencies, Docker recipes and production/Supabase
configuration remain unchanged. Changed shared CRM files retain their earlier
company/contact and drag-and-drop work; a future commit must isolate task hunks.
