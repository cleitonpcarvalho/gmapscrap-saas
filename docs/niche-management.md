# Niche management and lead correction

## Architecture

The web app is Next.js/React. The API is FastAPI with SQLAlchemy and a direct
connection to Supabase PostgreSQL. Both clients authenticate with the backend's
signed session cookie; this project does not use Supabase Auth for application
sessions. The macOS app uses PySide6 and the same authenticated HTTP API.

`leads` stores `run_id`; its `niche` and `location` API properties come from
`search_runs.niche` and `search_runs.location`. There is no `locality` column.
Search runs also contain scraper options, progress, timestamps and history.

The new `niches` registry is independent of these tables. Renaming or deleting a
registered niche changes suggestions only. Existing leads, search labels,
filters, run IDs and scraper behavior remain intact. Searches still accept a
string `niche`, including values not registered in the catalog. Creating a
registry entry is an explicit action; old searches are not seeded automatically.

## API and UI

All routes require the existing valid GmapScrap session:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/api/niches?q=brin` | List alphabetically; optional literal substring filter |
| GET | `/api/niches/{id}` | Read one entry |
| POST | `/api/niches` | Create from `{"name":"Brindes"}`; returns 201 |
| PATCH | `/api/niches/{id}` | Rename using the same payload |
| DELETE | `/api/niches/{id}` | Remove the catalog entry only |

Names use the same label normalization as search input, collapse whitespace, and
must contain 2–255 characters after normalization. Control characters, unknown
fields and null names are rejected (422). Case-insensitive duplicates return 409,
including database uniqueness conflicts; missing entries return 404. The database
also enforces nonempty trimmed names and a unique `lower(name)` index.

In **Nova busca**, the web niche field offers registered suggestions. **Gerenciar
nichos / cadastrar novo** opens the searchable CRUD manager; creating or selecting
an entry fills the search field. Suggestions also appear when adding/editing a
lead. Deletion requires confirmation in the manager.

On macOS, the niche field supports case-insensitive substring completion.
**Atualizar nichos** reloads the catalog; **Cadastrar nicho** explicitly saves the
typed value and selects the result. Registry network calls run in a separate
thread. If an older API lacks these routes or is offline, free-text search remains
available and an error is logged. Rebuild the macOS app using the existing
`desktop/build_macos_app.sh` process when distributing the change.

## Database migration — applied to production

`migrations/20261119_niches.sql` creates only the new registry, index and check
constraint. It enables RLS and revokes table/sequence privileges from `PUBLIC`,
`anon` and `authenticated`. There are no public RLS policies: clients must use
the GmapScrap API, which validates the signed session. The backend database
connection must use the table owner or a trusted BYPASSRLS role. This matches the
current direct Supabase PostgreSQL connection.

The SQL is transactional and repeatable. It was applied to production on
19 November 2026 after checksum verification and an isolated restoration of the
full database backup. All 761 leads and 40 historical searches were verified
unchanged by content hashes. The table, indexes, constraints, backend access and
RLS were verified. Do not reapply the migration as part of application deployment.

For fresh databases, the existing SQLAlchemy startup mechanism creates the table
and applies access controls inside the table-creation transaction. The creation
hook does not run for an existing table. No API keys are added to either client.

See [Supabase RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security)
for the default-deny behavior of an RLS table without policies.

## Production correction — awaiting explicit approval

The database was inspected in a PostgreSQL-enforced **read-only, repeatable-read**
transaction. The saved preview is `docs/lead-segment-correction-preview.json`.
At 15:01:24 on 19 November 2026 (America/Fortaleza), the exact intersection
`niche = 'São José do Rio Preto' AND location = 'Brindes'` matched:

- **6 leads:** 768, 769, 770, 771, 772, 773.
- **Search runs:** 39, 40.
- Proposed values: niche **Brindes**, location **São José do Rio Preto**.

`scripts/preview_lead_segment_correction.py --output <file.json>` regenerates the
preview with the configured database credentials. It has no write/apply option,
does not import the application startup, and does not run schema migrations.

`scripts/lead_segment_correction_PROPOSED.sql` is a review-only correction. It
locks membership and verifies the exact approved IDs before changing only the
two label fields in search runs 39 and 40. This necessarily corrects the labels
displayed in those two historical searches, because leads inherit those labels.
It preserves all search rows, progress, timestamps, options, lead fields and
relationships. It refuses changed membership and defaults to **ROLLBACK**.
This correction has not been executed. A refreshed preview and explicit user
approval are required before a future production
correction; approval of the feature does not authorize correcting data.

## Validation

Use an isolated environment with project dependencies, pytest and httpx. For the
desktop tests, also install `desktop/requirements.txt`; they skip if PySide6 is
unavailable. Set `QT_QPA_PLATFORM=offscreen` for headless desktop checks.

```sh
DB_HOST='' DB_NAME='' DB_USER='' DATABASE_URL='sqlite://' QT_QPA_PLATFORM=offscreen python -m pytest -q
cd frontend
npm run build
```

PostgreSQL tests are opt-in using `GMAPSCRAP_TEST_POSTGRES_URL`. Use a disposable
test database with schema/role creation privileges, **never production**. Tests
create and remove isolated schemas and a temporary test role. They cover the
additive repeatable migration, startup RLS protection, denied reads/writes,
rollback default, exact correction scope, and refusal of changed membership.
Where `anon`/`authenticated` test roles exist, they also simulate Supabase default
grants and verify that the migration revokes them.

API tests cover CRUD, normalization, validation, literal filtering, duplicate
conflicts, authentication, missing IDs, legacy free-text search requests and
preservation of every lead/search field. Desktop tests cover substring
completion, explicit creation, failure handling and request routing.

For a release that must not execute the proposed lead correction even in a test
database, exclude its two execution tests:

```sh
python -m pytest -q \
  --deselect=tests/test_postgres_niches.py::test_proposed_correction_rolls_back_by_default_and_changes_only_approved_fields \
  --deselect=tests/test_postgres_niches.py::test_correction_refuses_changed_lead_membership
```

The 19 November 2026 application release passed **173 tests**, with only these two
correction tests deselected. PostgreSQL tests used a fresh local PostgreSQL 17
database with simulated Supabase API roles; the production niche migration was
not rerun. The frontend production build and TypeScript check also passed.

Verified on 19 November 2026: **175 tests passed**, including the PostgreSQL tests
against a disposable local PostgreSQL 17 instance with simulated Supabase API
roles. `npm run build`, TypeScript `--noEmit` and `git diff --check` passed.
The existing uncommitted `docker-compose.prod.yml` diff was preserved byte for
byte. A live web visual walkthrough was attempted, but the browser connector
failed before opening the local preview; no browser walkthrough is claimed.
