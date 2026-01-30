from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.append(str(SRC))

os.environ.setdefault("RECEIPTGATE_ALLOW_INSECURE_DEV", "true")
os.environ.setdefault("RECEIPTGATE_API_KEY", "test-key")

from receiptgate.config import settings
from receiptgate.db import apply_schema, DB


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "receiptgate.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "allow_insecure_dev", True)
    monkeypatch.setattr(settings, "enable_graph_layer", True)
    monkeypatch.setattr(settings, "enable_semantic_layer", True)

    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    apply_schema(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    db_path = tmp_path / "receiptgate_api.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "allow_insecure_dev", True)
    monkeypatch.setattr(settings, "enable_graph_layer", True)
    monkeypatch.setattr(settings, "enable_semantic_layer", True)
    monkeypatch.setattr(settings, "auto_migrate_on_startup", True)

    DB.engine = None
    DB.SessionLocal = None

    from fastapi.testclient import TestClient
    from receiptgate.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client
