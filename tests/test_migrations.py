from __future__ import annotations

from sqlalchemy import create_engine, text

from receiptgate.config import settings
from receiptgate.db import apply_schema


def _index_names(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA index_list('{table}')")).mappings().all()
    return {row["name"] for row in rows}


def test_apply_schema_creates_tables_and_indexes(tmp_path, monkeypatch):
    db_path = tmp_path / "migrations.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "enable_graph_layer", True)
    monkeypatch.setattr(settings, "enable_semantic_layer", True)

    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    apply_schema(engine)

    with engine.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).mappings()
        }
        assert "receipts" in tables
        assert "receipt_edges" in tables
        assert "receipt_embeddings" in tables
        assert "receipts_v1" in tables

        receipt_indexes = _index_names(conn, "receipts")
        assert "idx_receipts_caused_by" in receipt_indexes
        assert "idx_receipts_inbox_open" in receipt_indexes
        assert "idx_receipts_obligation" in receipt_indexes

        edge_indexes = _index_names(conn, "receipt_edges")
        assert "idx_receipt_edges_to" in edge_indexes

        v1_indexes = _index_names(conn, "receipts_v1")
        assert "idx_receipts_v1_tenant_receipt" in v1_indexes
        assert "idx_receipts_v1_inbox" in v1_indexes
        assert "idx_receipts_v1_task" in v1_indexes
        assert "idx_receipts_v1_caused_by" in v1_indexes

    engine.dispose()
