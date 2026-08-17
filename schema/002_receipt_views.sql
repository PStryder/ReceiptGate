BEGIN;

-- Dependents are dropped before their dependencies, v_inbox before
-- v_open_obligations. The drops used to run in creation order, which is a no-op
-- on an empty database and fatal on every re-apply: Postgres refuses to drop
-- v_open_obligations while v_inbox selects from it. Migrations run on startup,
-- so ReceiptGate could be started but never restarted -- the ledger came back
-- only if its volume was destroyed first. CASCADE would also work and would
-- also silently drop anything else that had come to depend on these.
DROP VIEW IF EXISTS v_inbox;
DROP VIEW IF EXISTS v_open_obligations;

-- Open obligations: accepted receipts not yet terminated by a terminal receipt.
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
CREATE VIEW v_inbox AS
SELECT * FROM v_open_obligations;

COMMIT;
