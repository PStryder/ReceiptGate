BEGIN;

-- Open obligations: accepted receipts not yet terminated by a terminal receipt.
DROP VIEW IF EXISTS v_open_obligations;
CREATE VIEW v_open_obligations AS
SELECT r.*
FROM receipts r
WHERE r.phase = 'accepted'
AND NOT EXISTS (
  SELECT 1 FROM receipts t
  WHERE t.obligation_id = r.obligation_id
    AND t.phase IN ('complete', 'escalate', 'cancel')
);

-- Inbox: open obligations per recipient.
DROP VIEW IF EXISTS v_inbox;
CREATE VIEW v_inbox AS
SELECT * FROM v_open_obligations;

COMMIT;
