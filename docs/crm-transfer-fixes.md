# CRM pipeline and stage transfer fixes

Implemented locally on 2026-11-21 for the separately authorized Phase 1
application rollout. These fixes require no additional database migration.

## Cause and implementation

The populated-delete handlers changed only scalar `stage_id` / `funnel_id`
values. SQLAlchemy's already-loaded `back_populates` collections still contained
the moved cards. Deleting the old parent consequently attempted to set their
required foreign keys to NULL.

`backend/services/crm_transfers.py` now owns both workflows. It assigns the
`stage_ref` and `funnel` relationships, synchronizes the stage key and position,
and flushes all moves and new history entries before removing the parent. Stage
removal uses the existing delete-orphan relationship so its loaded pipeline
collection also stays consistent. The authenticated DELETE endpoints and their
`status` / `moved_cards` responses remain compatible.

Each operation has one commit. Validation errors, uniqueness conflicts, stale
versions and any later failure roll back the entire operation. Expected
concurrency conflicts return HTTP 409. Participating pipelines, cards and stages
are locked in deterministic ID order; pipeline locks also block FK-backed
membership inserts while the transfer is being completed.

## Transfer and preservation rules

- A populated stage requires a different destination stage in the same pipeline.
  Its cards are appended in their existing order after destination cards.
- A populated pipeline requires a different destination pipeline with stages.
  Matching stage keys are retained where available; unmatched cards enter the
  first destination stage. Existing destination cards are not renumbered.
- If any source lead already has a card in the destination pipeline, the entire
  request returns 409 without changes. Neither opportunity is merged or deleted.
  Independent memberships in other pipelines remain intact. The existing unique
  membership constraint also protects against a late conflicting insert.
- Default pipelines and the final stage of a pipeline remain protected.
- Card IDs, qualification notes, activity entries, follow-ups, sales outcomes,
  values, currencies and manual-management flags are retained. Transfer updates
  membership/order, the card modification timestamp and optimistic version. Won
  stage flags never manufacture a confirmed sales outcome.
- Existing stage-history rows, stage-key text, authors and timestamps remain.
  As before, their foreign-key pointers to physically deleted stages become NULL
  through the existing `ON DELETE SET NULL` constraints. Each moved card receives
  a new stage-history entry. Manual opportunities also receive an append-only
  system activity containing source/destination pipeline and stage IDs, keys and
  labels, preserving transfer context after parent deletion.
- Leads, search history, niches, tags and WhatsApp records are not changed.
  Manual transfer does not call Evolution API or enable AI automation.

## Validation

- Full backend/API/desktop/PostgreSQL suite: **240 passed**, no skips, four
  existing deprecation warnings.
- Frontend suite: **15 passed**.
- Linux amd64 production backend Docker image: built successfully; imports and
  both DELETE routes checked with networking disabled and an isolated DB URL.
- **18 new real PostgreSQL cases** cover populated transfers, preloaded ORM
  collections, duplicate memberships, rollback after flushed changes, late
  uniqueness failure, invalid destinations, protected parents, lock timeouts and
  membership insertion during transfer. Tests apply pending Phase 1 and security
  migrations only to disposable loopback databases and use the postgres owner
  without SUPERUSER or BYPASSRLS. Manual detail, optimistic editing, append-only
  activities and follow-up completion work after transfer.
- The security compatibility probe exercises the deployed release and current
  working tree before/after hardening. Only archived code reproduces the two
  original NULL-FK failures; current handlers pass.

No new migration is required for these fixes. The existing
`20261121_manual_crm_phase1.sql` and `20261121_crm_security.sql` files were not
changed by the transfer implementation. Both were separately applied and
verified in production on 2026-11-22; do not rerun them during deployment.
Docker, Traefik and production settings are preserved.
