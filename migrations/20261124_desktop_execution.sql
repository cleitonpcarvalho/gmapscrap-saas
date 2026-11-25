-- Apply only as part of a separately approved backend deployment.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '45s';
ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS execution_source VARCHAR(20) NOT NULL DEFAULT 'server';
ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS desktop_request_id VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_search_runs_desktop_request_id ON search_runs (desktop_request_id);
COMMIT;
-- Historical runs cannot be reliably classified from their mutable messages.
-- Review any legacy queued/running/paused desktop run IDs before backend restart;
-- assign execution_source='desktop' only to explicitly verified IDs.
