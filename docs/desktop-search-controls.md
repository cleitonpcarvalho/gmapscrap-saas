# Desktop niche picker and execution controls

The desktop app uses PySide6. One `SearchWorker` runs in one `QThread`; Selenium
and email extraction run in that worker. History and niche requests have separate
read-only threads, so slow API reads cannot block the Pause/Stop buttons.

## Niche picker

Focusing or clicking the editable input opens the complete registered list,
including when the input is empty. Typing filters by case-insensitive substring.
Mouse selection and arrow keys/Enter accept a suggestion; Escape or an outside
click closes the popup. Free text is still accepted. The production niche API
contract is unchanged.

## Pause, Resume and Stop

- **Pausar** requests cooperative cancellation, closes the generator and Chrome,
  and acknowledges `paused` through the API. It keeps the same search ID.
- **Retomar** reuses that ID and the last handled result's cursor. An unfinished
  email lookup does not advance the cursor. It does not create another search.
- **Parar busca** cancels the current execution permanently, including while
  paused, and acknowledges the terminal state `stopped`. Existing leads remain.
  A stopped search cannot be resumed by this app or by the updated backend.
- Stop takes priority over Pause. A stop accepted before finalization cannot be
  reported as completed. Controls remain busy until the worker thread exits.
- Cancellation prevents new scraping/API requests. A lead request already sent
  may finish before Stop is acknowledged; it remains saved. The local worker
  waits for that request and does not send another lead. Network operations are
  bounded by their timeouts (up to 60 seconds for an in-flight ingestion).
- Chrome cleanup tries Selenium `quit()` first, then terminates/kills only the
  owned ChromeDriver process and its captured descendants. It removes that
  search's temporary profile. A canceled driver startup cannot start a new
  session once cancellation is observed. Driver resolution/download may still
  need to finish before the constructor returns.
- A per-user lock prevents two new app instances from running simultaneously.
  Search creation is never automatically retried against the legacy API.

Final API updates use a credential-free durable outbox at
`~/Library/Application Support/GmapScrap/pending-search.json`. An unsuccessful
update blocks new searches and Resume until **Tentar sincronizar** succeeds.
Restarting the app restores that pending state. A lost creation response is also
journaled, so another execution is not silently created. After the backend
update, recovery resolves the original creation key and finalizes that run.

## Compatibility with the current production backend

The current production schema accepts only `running`, `paused`, `completed` and
`failed` in desktop PATCH requests. If it rejects `stopped` with HTTP 422, the
new app uses the terminal status `failed`, with `error=DESKTOP_STOPPED`. The new
desktop displays that combination as **Parada**, never **Concluída**. The current
backend rejects ingestion into `failed` runs. The web UI may display **Falhou**
until it learns this marker or the backend is updated.

The legacy backend does not enforce immutable terminal transitions or desktop
execution ownership. Those server-side protections require the separate backend
update described below. If a creation response is lost against the legacy API,
automatic recovery by creation key is unavailable: the app stays blocked pending
manual review of the search history and outbox. Do not delete that outbox or
repeat creation until the ambiguous execution has been reconciled.

## Backend deployment requirements — implemented locally, not deployed

1. Review/apply `migrations/20261124_desktop_execution.sql` with the backend
   release. It adds `execution_source` and the unique nullable
   `desktop_request_id`; no lead rows are rewritten. The existing startup column
   migration also installs these additive columns/index for local databases.
2. Deploy the matching backend code. It accepts `stopped`, rejects late ingestion
   and reopening of terminal runs, and serializes ingestion/status changes with
   a PostgreSQL advisory lock held across helper commits. An in-flight ingestion
   finishes before the Stop response; requests after that response are rejected.
3. New desktop rows have `execution_source=desktop`. Startup and web Resume never
   submit them to the server scraper. Idempotency keys prevent duplicate creation;
   authenticated `GET /api/desktop/searches/by-request/{key}` resolves lost replies.
4. Before restarting a backend with historical active searches, explicitly review
   legacy desktop run IDs. Old rows default to `server`, because mutable messages
   cannot reliably establish ownership. Reclassify only verified IDs in a
   separately approved deployment. This task did not reclassify production rows.

No backend deployment, production migration, live search, or production data
mutation was performed during this implementation or its validation.

## Validation and build

Regression tests cover actual Qt picker interactions, Pause/Resume/Stop, cursor
preservation, cancellation during enrichment, late writes, terminal-state
immutability, lost-response recovery, API compatibility and process ownership.
The database tests use a disposable PostgreSQL cluster on local port 55488.
An opt-in `GMAPSCRAP_TEST_CHROME=1` integration test starts real headless Chrome
with an isolated profile and a local `data:` page, then verifies driver/browser
cleanup. It does not scrape Google Maps or call the production API.

Build with a Python 3.12 virtual environment containing
`desktop/requirements.txt` and PyInstaller:

```sh
PYTHON_BIN=/path/to/venv/bin/python desktop/build_macos_app.sh
```

`DIST_DIR`, `BUILD_WORK_DIR`, and `BUILD_SPEC_DIR` can stage a release before
replacement. Existing icon assets are reused unless their source changes or
`REGENERATE_ICON=1`. The app embeds `Contents/Resources/build-info.json` with the
Fortaleza build timestamp, source hashes, Git base commit and component versions.
Credentials remain in the existing external environment file; they are not
included in the build metadata.
