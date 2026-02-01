"""
Builds receipt_edges from receipts.caused_by_receipt_id.
Idempotent: rebuildable from canon.
"""

import os

import psycopg

EDGE_TYPE = "caused_by"

SQL_CLEAR = "DELETE FROM receipt_edges WHERE edge_type = %s;"
SQL_INSERT = """
INSERT INTO receipt_edges (from_receipt_id, to_receipt_id, edge_type)
SELECT receipt_id, caused_by_receipt_id, %s
FROM receipts
WHERE caused_by_receipt_id IS NOT NULL
ON CONFLICT DO NOTHING;
"""


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_CLEAR, (EDGE_TYPE,))
            cur.execute(SQL_INSERT, (EDGE_TYPE,))
        conn.commit()


if __name__ == "__main__":
    main()
