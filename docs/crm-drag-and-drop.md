# Commercial CRM drag-and-drop repair

## Root cause

Commit `d7e7ea7` routed `/crm` to the new `ManualCrmWorkspace` and retained the
previous board at `/whatsapp/crm`. The commercial renderer emitted plain card
buttons and stage sections. It never mounted a dnd-kit context, sensors,
`useSortable`, droppable stages, or drag handlers. The shared CSS still displayed
a grab cursor, making the cards appear draggable despite having no behavior.

The previous WhatsApp board in `frontend/app/page.tsx` already used dnd-kit
contexts, sortable cards, droppable columns, an overlay, and optimistic updates.
Those controls were scoped to the WhatsApp renderer. The commercial API also
lacked the `position` field in its versioned PATCH input, so it could change a
stage from the detail form but could not persist order. Both omissions were
identified before modifying application code.

## Implementation

The commercial board now uses the already-installed `@dnd-kit/core` and
`@dnd-kit/sortable`. Mouse movement activates after eight pixels, touch uses a
short hold, and keyboard interaction uses Space, arrow keys and Escape. Dragged
cards have an overlay, stages highlight as targets, and the board auto-scrolls
horizontally near its edges. Clicking a card still opens its commercial details.
The board also follows dnd-kit's actual active context: a mouse gesture ending
before the sensor snapshot commits cannot leave stale dragging feedback or
permanently suspend refreshes. Such an incomplete gesture is safely cancelled.

The board uses card IDs, not lead IDs, to distinguish opportunities for the same
company in different pipelines. A pure move planner changes only stage and
position, compacts the affected source/destination lists and preserves all other
commercial data.

Persistence uses the existing authenticated endpoint:

```http
PATCH /api/crm/manual/cards/{card_id}
Content-Type: application/json

{"version": 3, "stage_id": 8, "position": 0}
```

Only one mutation can be in flight. Optimistic changes roll back on a failed
PATCH, with a refresh required before another attempt. A successful PATCH is
followed by a full pipeline read, because neighbor positions and versions also
change. If that read fails, the committed move is retained and dragging remains
disabled until a successful refresh. This avoids presenting an unsaved move or
sending stale versions. Polls already in flight are invalidated when dragging
starts, and stale responses cannot replace a newly selected pipeline.

The backend extends the existing PATCH model with `position`, locks the pipeline
before the card (matching additions and transfers), checks the card version,
and performs normalization and activity/history insertion in one transaction.
Stale or invalid operations cannot partially reorder a pipeline. No endpoint,
package, table or migration was added.

Stage movement does **not** infer a won/lost outcome. The existing commercial
model requires explicit outcome confirmation: won opportunities need a proposal
value, lost opportunities need a reason. The existing API validation remains in
force, including rollback when combined stage/outcome edits are invalid. Moving
a legacy card preserves its unconfirmed outcome and does not silently assume
manual management. Notes, existing activities, follow-ups, proposal values,
closed dates, source leads and opportunities in other pipelines are preserved;
movement adds an audit event instead of replacing historical records.

## Changed files

- `frontend/app/components/crm/ManualCrmBoard.tsx`: drag sensors, sortable cards,
  drop targets, overlay, keyboard interaction and horizontal auto-scroll.
- `frontend/app/components/crm/board.ts`: validated pipeline membership and
  immutable stage/order planning.
- `frontend/app/components/crm/ManualCrmWorkspace.tsx`: API persistence,
  optimistic rollback, canonical reconciliation and refresh/race guards.
- `frontend/app/components/crm/types.ts`: card position metadata.
- `frontend/app/globals.css`: scoped dragging/drop-target feedback.
- `backend/manual_crm.py`: versioned position updates and transactional locking.
- `frontend/tests/manual-crm-dnd.test.tsx`: 14 additional frontend regressions.
- `tests/test_manual_crm_dnd.py`: preservation, ordering, validation and version
  conflict regressions.
- `tests/test_postgres_manual_crm_dnd.py`: concurrent moves and preservation on
  real PostgreSQL with the existing CRM security migrations.
- `docs/crm-drag-and-drop.md`: investigation, behavior and release requirements.

## Validation — November 24, 2026

- Full frontend suite: **29 passed**. It exercises the real dnd-kit sensors and
  sortable components with measurable jsdom geometry, including mouse and
  keyboard moves, same-stage reordering, target feedback, horizontal auto-scroll,
  cancellation, fast-gesture cleanup, duplicate blocking, API errors, reconciliation and pipeline races.
- `npx tsc --noEmit`: **passed**.
- `npm run build`: **passed**, including `/crm` and `/whatsapp/crm`.
- Relevant backend CRM suites: **64 passed**, including real concurrent
  PostgreSQL moves, ordering consistency, rollback and data preservation.
- Native Chrome with a synthetic localhost API: keyboard movement emitted
  exactly one versioned PATCH containing only stage/order fields; the changed
  stage persisted after reload. Mouse and edge-scroll behavior were also covered
  by the automated sensor tests. No live card was moved.

Database tests used disposable databases on localhost port 55488. Browser checks
used localhost ports 13098 and 18098 with synthetic cards and no database. All
temporary services were shut down after validation.

## Deployment requirements

Release the updated manual CRM API before, or together with, the frontend. An
older backend rejects the new `position` field; the UI will roll back and show
that error until the API is updated. The existing manual CRM schema/security
migrations are prerequisites already required by the commercial workspace; this
repair adds no schema changes or dependencies.

Nothing was deployed. Production data was not changed. The macOS desktop app,
Docker files, Supabase configuration, frontend dependency manifests, and the
previous WhatsApp board were not modified by this repair. Task-start hashes were
used to distinguish these changes from earlier uncommitted work in the checkout.
