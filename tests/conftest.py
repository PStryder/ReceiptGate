from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.append(str(SRC))

os.environ.setdefault("RECEIPTGATE_ALLOW_INSECURE_DEV", "true")
os.environ.setdefault("RECEIPTGATE_API_KEY", "test-key")

from receiptgate.config import settings
from receiptgate.db import DB, apply_schema

# ReceiptGate runs on Postgres. The suite runs against it when one is reachable
# and falls back to SQLite otherwise, because a fast local loop is worth having
# and most of these tests are about logic rather than storage.
#
# The distinction is not cosmetic. SQLite serializes writers behind a
# database-level lock, so two acceptances of one obligation cannot interleave --
# the exclusion tests pass there without the race ever occurring. Only Postgres
# can demonstrate that the partial unique index is what decides the winner
# rather than the timing, which is the whole Phase 2 claim. Tests that depend on
# that are marked `requires_postgres` and skip with a reason on SQLite, so a
# SQLite run reports honestly instead of implying it proved something.
TEST_POSTGRES_URL = os.environ.get("RECEIPTGATE_TEST_DATABASE_URL")


def _postgres_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = bool(TEST_POSTGRES_URL) and _postgres_reachable(TEST_POSTGRES_URL)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_postgres: needs real concurrent transactions; SQLite cannot "
        "exercise the interleaving these assert",
    )


def pytest_collection_modifyitems(config, items):
    if POSTGRES_AVAILABLE:
        return
    skip = pytest.mark.skip(
        reason="needs Postgres: SQLite serializes writers, so the race under "
        "test cannot occur and passing would prove nothing. Set "
        "RECEIPTGATE_TEST_DATABASE_URL to run it."
    )
    for item in items:
        if "requires_postgres" in item.keywords:
            item.add_marker(skip)


def _fresh_schema_url(tmp_path, name: str) -> str:
    """A database URL with the schema applied and nothing else in it.

    On Postgres each test gets its own schema rather than its own database, so
    tests are isolated without the cost of a CREATE DATABASE per test.
    """
    if POSTGRES_AVAILABLE:
        return TEST_POSTGRES_URL
    return f"sqlite:///{tmp_path / name}"


def _reset_postgres(engine) -> None:
    """Drop and recreate the public schema so each test starts empty."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture()
def db_url(tmp_path) -> str:
    """The database URL under test, Postgres when one is available."""
    return _fresh_schema_url(tmp_path, "receiptgate.db")


@pytest.fixture()
def db_session(db_url, monkeypatch):
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "allow_insecure_dev", True)
    # Both off, matching the demo stack. They were on here and harmless only
    # because SQLite ignores unknown column types: 004 declares pgvector's
    # `vector`, which real Postgres rejects with `type "vector" does not
    # exist`. So the suite was validating against a schema the production
    # database could not create. Both layers are dead code besides -- the
    # graph job reads a table nothing writes and the embedding job raises
    # NotImplementedError.
    monkeypatch.setattr(settings, "enable_graph_layer", False)
    monkeypatch.setattr(settings, "enable_semantic_layer", False)

    connect_args = {} if POSTGRES_AVAILABLE else {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args)
    if POSTGRES_AVAILABLE:
        _reset_postgres(engine)
    apply_schema(engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def mcp_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", exc_type=ImportError)
    url = _fresh_schema_url(tmp_path, "receiptgate_api.db")
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "allow_insecure_dev", True)
    # Both off, matching the demo stack. They were on here and harmless only
    # because SQLite ignores unknown column types: 004 declares pgvector's
    # `vector`, which real Postgres rejects with `type "vector" does not
    # exist`. So the suite was validating against a schema the production
    # database could not create. Both layers are dead code besides -- the
    # graph job reads a table nothing writes and the embedding job raises
    # NotImplementedError.
    monkeypatch.setattr(settings, "enable_graph_layer", False)
    monkeypatch.setattr(settings, "enable_semantic_layer", False)
    monkeypatch.setattr(settings, "auto_migrate_on_startup", True)

    if POSTGRES_AVAILABLE:
        engine = create_engine(url)
        _reset_postgres(engine)
        engine.dispose()

    DB.engine = None
    DB.SessionLocal = None

    from fastapi.testclient import TestClient

    from receiptgate.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client
    DB.engine = None
    DB.SessionLocal = None
