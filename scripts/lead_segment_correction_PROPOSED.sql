-- REVIEW ONLY. Do not execute without the user's explicit approval.
-- Preview: docs/lead-segment-correction-preview.json (2026-11-19).
-- Labels are inherited from search_runs. SET changes exactly two fields.
-- Search rows, lead run_id, counts, timestamps and every other field are preserved.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '30s';

-- Freeze membership while checking that the reviewed lead set has not changed.
LOCK TABLE leads IN SHARE MODE;
SELECT id FROM search_runs WHERE id IN (39, 40) ORDER BY id FOR UPDATE;
DO $$
DECLARE matched_ids integer[];
DECLARE run_lead_ids integer[];
DECLARE changed integer;
BEGIN
    SELECT array_agg(l.id ORDER BY l.id) INTO matched_ids
    FROM leads l JOIN search_runs r ON r.id = l.run_id
    WHERE r.niche = 'São José do Rio Preto' AND r.location = 'Brindes';

    SELECT array_agg(id ORDER BY id) INTO run_lead_ids
    FROM leads WHERE run_id IN (39, 40);

    IF matched_ids IS DISTINCT FROM ARRAY[768, 769, 770, 771, 772, 773]
       OR run_lead_ids IS DISTINCT FROM matched_ids THEN
        RAISE EXCEPTION 'Lead set changed since preview. Stop and generate a new preview.';
    END IF;

    UPDATE search_runs
    SET niche = 'Brindes', location = 'São José do Rio Preto'
    WHERE id IN (39, 40) AND niche = 'São José do Rio Preto' AND location = 'Brindes';
    GET DIAGNOSTICS changed = ROW_COUNT;
    IF changed <> 2 THEN
        RAISE EXCEPTION 'Expected exactly two search runs, found %.', changed;
    END IF;
END $$;

SELECT l.id, l.run_id, r.niche, r.location
FROM leads l JOIN search_runs r ON r.id = l.run_id
WHERE l.id IN (768, 769, 770, 771, 772, 773) ORDER BY l.id;

ROLLBACK; -- Keep this default. COMMIT requires explicit approval of this correction.
