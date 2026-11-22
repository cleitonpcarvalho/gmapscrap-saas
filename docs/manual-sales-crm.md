# Manual sales CRM — phase 1

The security and Phase 1 database migrations were applied and verified on
2026-11-22, before the separately authorized application rollout. Do not rerun
them during deployment. Authentication continues to use the existing single
login. Docker, Traefik, production settings,
scraping contracts, niche registry, and desktop search contracts are unchanged.

## Interface

- `/crm` is the independent commercial workspace. The previous WhatsApp board,
  including its drag-and-drop controls, remains at `/whatsapp/crm`.
- **Leads → Adicionar ao CRM** opens a server-paginated selector with company,
  niche and locality filters. Its selection survives page/filter changes and
  can reach the whole database, independently of the legacy table's 500-row
  response limit. Select up to 1,000 leads per transaction and choose a pipeline
  and initial stage. Existing memberships are reported and left unchanged.
- New cards append to the chosen stage without rewriting existing positions.
  The unique `(lead_id, funnel_id)` constraint remains: a lead may be in several
  pipelines, but only once in each pipeline.
- Dedicated details show shared company/contact data, niche/locality, tags,
  current pipeline/stage, and a separate collapsible scraping provenance area.
  Commercial operations never reassign `leads.run_id` or change search fields.
- Contact links use local phone normalization, without an Evolution request or
  requiring a successful WhatsApp validation. Opening a link does not record
  an activity or assert delivery. A user logs the actual interaction separately.
- Notes, calls, WhatsApp contacts and meetings append immutable timeline entries.
  Original `qualification_notes` and stage changes remain visible as legacy
  records. No authorship or note-creation date is invented for old records.
- Follow-ups can be created, rescheduled, completed or cancelled. Each change
  appends a permanent event. Cards show the earliest pending follow-up; completed
  and cancelled tasks retain their records.
- Overdue means before the current instant; Today means remaining instants before
  the next local midnight; Upcoming starts at that midnight. UTC timestamps are
  displayed in the browser's local timezone, with DST-aware server boundaries.
- Proposal values use `NUMERIC(14,2)`, never floating-point storage. Supported
  currencies are BRL, USD, EUR, GBP, CAD and AUD. Won/lost are explicit sales
  outcomes, independent of stage names. Lost requires a reason; won requires an
  entered proposal value. Reopening clears the current close time while keeping
  its immutable event history. Editing a lost reason retains the close time.

## Legacy and automation behavior

The migration sets no historical sales outcomes. Old cards remain legacy records
with `sales_outcome = NULL`, and a legacy Convertido stage is not confirmed sales
revenue. **Assumir gestão manual** is an explicit user action: it preserves stage,
notes and history, and starts the commercial outcome as open.

Manual cards have `managed_manually = true`. AI stage/note tools cannot move them;
AI tag and stage tools and webhook card creation also abstain for any lead with a
manual card, avoiding ambiguous changes across pipelines with shared lead tags.
Webhook creation and AI stage ordering also leave neighboring manual cards,
including their positions, timestamps and versions, unchanged.
Inbound conversations continue to be ingested and existing AI reply settings are
respected. No automation is enabled by this feature. Legacy automation for other
leads remains available. Direct updates to old qualification notes are rejected
for manual cards; the timeline is used instead.

The commercial page never loads WhatsApp/AI endpoints. Pipeline management also
refreshes CRM data independently. Default-stage definitions are seeded only for
an empty pipeline: neither GET requests nor startup reseeding overwrite stage
customizations or restore deliberately removed stages.

## API

All `/api/crm/manual/*` routes require the existing signed session cookie and use
the backend connection. Strict write models reject unknown fields. No direct
Supabase browser access is added.

| Method/path | Behavior |
| --- | --- |
| GET `/leads?q=&niche=&location=&offset=&limit=` | Server-filtered company picker; 30 per page by default, maximum 100. Also accepts tag IDs. |
| POST `/cards` | Atomic lead-ID selection, pipeline ID, stage ID; returns created card IDs and skipped existing lead IDs. |
| GET `/cards?funnel_id=` | Cards and next pending follow-up, without provider calls. |
| GET `/cards/{id}` | Commercial details, activities, stage history, legacy notes and follow-ups. |
| PATCH `/cards/{id}` | Required version; manual takeover, stage, estimated value, currency, explicit outcome and lost reason. |
| POST `/cards/{id}/activities` | Append note/call/WhatsApp/meeting; server timestamp and authenticated actor. |
| POST `/cards/{id}/follow-ups` | Title plus timezone-aware due time. |
| PATCH `/follow-ups/{id}` | Required version and complete/reschedule/cancel action. |
| GET `/follow-ups?bucket=&timezone_name=` | Pending overdue/today/upcoming tasks, across pipelines. |

Card/follow-up versions reject stale updates with HTTP 409. Invalid batch members
or stages abort the whole batch. Validation after a stage/value edit rolls back
the edit and its events together. Existing individual/bulk lead deletion refuses
manual opportunities rather than cascading away commercial history.

## Required migration and rollout prerequisites

`migrations/20261121_manual_crm_phase1.sql` is a separately reviewed, explicit
transactional PostgreSQL migration. It adds seven fields to `crm_leads` and creates
`crm_activities` and `crm_follow_ups`, their sequences, indexes, foreign keys,
checks, and activity immutability triggers. Existing card fields, lead/search
rows, tags, pipelines, stages and stage history are not rewritten.

The new tables enable RLS and revoke table/sequence privileges from PUBLIC,
anon and authenticated. The existing backend owner retains access. If changing
to a non-owner backend role later, explicitly grant that role only the required
table/sequence access and review its RLS policy; this migration adds no permissive
browser policies. Activity UPDATE, DELETE and TRUNCATE are rejected by PostgreSQL.

Application startup does not create the activity/follow-up tables or add these
columns to an existing CRM table. A migration-before-code rollout is required;
the new routes return 503 when their required schema is missing. Older CRM code
paths also need the new columns once this version is deployed.

The production rollout verified the November 21 restore-tested full backup,
applied security before Phase 1, and explicitly revoked anon/authenticated
EXECUTE on `public.gmapscrap_crm_activity_immutable()` in the Phase 1 transaction.
That extra function revoke is required when Supabase default function grants
are present; the historical SQL file is preserved as reviewed. Do not reapply
either migration as part of an application deploy. For a fresh installation,
review those function defaults and explicitly revoke browser execution after
creating the function. No niche migration/import or lead-correction SQL is part
of this feature. Prefer rolling application code back while retaining the additive
schema. Dropping new tables would lose activity history and is not a safe rollback.

## Validation

Release validation on 2026-11-22: **240 backend/API/desktop/PostgreSQL tests**
passed without skips, and **15 frontend tests** passed. The Next.js production
build and both `linux/amd64` Docker production image builds passed. Network-free
image checks verified backend imports/routes and frontend routes/static assets.
Four existing framework deprecation warnings remain. The production baseline
matched the completed migration audit: 761 leads, 40 searches, 16 niches, nine
CRM cards and seven stage-history entries; the new activity/follow-up tables
were empty. The November 21 backup checksums, complete archive read and prior
successful restore validation were reverified. No migrations are part of the
application deployment.

Production write smoke tests use deployed authenticated handlers in an isolated
ASGI app and a shared database transaction with nested savepoints. The outer
transaction is always rolled back, commits are prohibited, fixture IDs are
explicit, and writes to business records are rejected. This allows testing
immutable activities and populated transfers without leaving permanent test
notes, advancing sequences, enabling workers or contacting WhatsApp providers.
Public HTTP and browser checks independently verify the deployed interface and
authenticated reads. Compare complete row fingerprints and security metadata
after these checks, rather than deleting append-only production test activities.

Earlier local validation on 2026-11-21:

- Backend/API/desktop/PostgreSQL suite: **207 passed**, no skips. Four existing
  FastAPI/Starlette deprecation warnings remain.
- Frontend suite: **15 passed**, including cross-page selection, immutable notes,
  explicit legacy takeover/outcomes, local display of historical follow-up dates,
  UTC scheduling, and `/crm` with provider requests unavailable.
- Next.js production build and both Docker images passed for `linux/amd64`.
  Local tags: `gmapscrap-validation-backend:manual-crm-phase1-20261121` and
  `gmapscrap-validation-frontend:manual-crm-phase1-20261121`. Nothing was pushed.
- Network-disabled image smoke tests passed: backend imports/OpenAPI and nine
  manual CRM routes; frontend `/`, `/crm`, `/nichos`, `/whatsapp/crm`, and static
  assets returned HTTP 200. Loopback hostname was set only on the temporary smoke
  container; project configuration was not changed.
- Synthetic browser checks covered disconnected-provider CRM loading, preserved
  legacy information, notes, follow-up completion, and cross-page CRM insertion.
- Production configuration, Dockerfiles, and deployment workflow match their
  original tracked contents. Production was not accessed or changed. Temporary
  preview servers, test containers and the isolated PostgreSQL server were stopped.

Tests cover server pages beyond 500, cross-page selections, duplicate/multiple
pipeline memberships, transaction rollback, preserved source data/legacy notes,
explicit outcomes and monetary validation, append-only history, automation guards,
UTC/DST follow-ups, stale versions, authenticated access, default-stage preservation,
and the UI operating with WhatsApp endpoints unavailable.

The real PostgreSQL test creates and drops a unique disposable local database,
reconstructs the old schema, runs the migration twice, compares source rows,
checks RLS/privileges, and attempts forbidden activity writes. Its destructive
fixture operations are guarded to loopback port 55488. Never point tests at
production. Production connection settings and external integration keys were
overridden during validation. Browser validation used synthetic companies and
startup jobs were disabled.

## Deliberate phase-1 limits

- Single shared login: activity actor identifies that login, not separate people.
- Follow-up reminders are in-app views refreshed every minute; no email, push,
  WhatsApp, or closed-browser delivery is introduced.
- One opportunity per lead/pipeline, including closed opportunities. Repeated
  sales in the same pipeline need a later explicit data-model decision.
- Stage and outcome are separate. Users must explicitly confirm the commercial
  result; old stage labels/flags never manufacture revenue.
- The original broad lead table retains its existing response cap; the new CRM
  selector independently provides full server pagination.
- Existing startup migration helpers and legacy automation outside manual leads
  remain. Moving those to a dedicated migration/worker system is a separate task.
