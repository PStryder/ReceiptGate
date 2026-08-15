"""Database initialization and schema helpers for ReceiptGate."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from receiptgate.config import settings

logger = logging.getLogger(__name__)


class DB:
    """Database state holder."""

    engine = None
    SessionLocal = None


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_dir() -> Path:
    """Locate the SQL schema directory in both installed and checkout layouts.

    When pip-installed, `parents[2]` is the site-packages parent (e.g.
    /usr/local/lib/python3.11), so the repo-relative path does not exist. The
    schema files ship inside the package (see the wheel force-include in
    pyproject.toml), so prefer the package-local copy and fall back to the
    repo layout for editable/source checkouts.
    """
    override = os.environ.get("RECEIPTGATE_SCHEMA_DIR")
    if override:
        return Path(override)

    packaged = Path(__file__).resolve().parent / "schema"
    if packaged.is_dir():
        return packaged

    return _schema_root() / "schema"


def _strip_sql_comments(sql: str) -> str:
    """Remove line comments before splitting on semicolons.

    The splitter below is naive by design -- these are our own schema files,
    not arbitrary SQL -- but it used to split on every `;` including ones
    inside `--` comments. A comment containing ordinary prose punctuation
    therefore produced a fragment like `if the two disagree, the ledger is`
    which SQLite reported as `near "if": syntax error`, from a file that is
    perfectly valid SQL.

    That is a trap for whoever writes the next migration, so comments are
    stripped first. String literals are left alone: a `--` inside quotes is
    not a comment, and none of our schema files contain one.
    """
    out = []
    for line in sql.splitlines():
        in_string = False
        for i, ch in enumerate(line):
            if ch == "'":
                in_string = not in_string
            elif ch == "-" and not in_string and line[i : i + 2] == "--":
                line = line[:i]
                break
        out.append(line)
    return chr(10).join(out)


def _read_sql_file(path: Path) -> list[str]:
    sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
    statements = []
    for stmt in sql.split(";"):
        cleaned = stmt.strip()
        if not cleaned:
            continue
        upper = cleaned.upper()
        if upper == "BEGIN" or upper == "COMMIT":
            continue
        statements.append(cleaned)
    return statements


def apply_schema(engine) -> None:
    schema_dir = _schema_dir()
    if not schema_dir.exists():
        raise RuntimeError(f"Schema directory missing: {schema_dir}")

    files = sorted(schema_dir.glob("*.sql"))
    if not files:
        logger.warning("No schema files found; skipping migration")
        return

    with engine.begin() as conn:
        for path in files:
            if path.name.startswith("003") and not settings.enable_graph_layer:
                continue
            if path.name.startswith("004") and not settings.enable_semantic_layer:
                continue
            for statement in _read_sql_file(path):
                conn.exec_driver_sql(statement)


def init_db() -> None:
    """Initialize database connection and optionally apply schema files."""
    engine_kwargs = {"pool_pre_ping": True}
    if settings.db_backend == "sqlite":
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    DB.engine = create_engine(settings.database_url, **engine_kwargs)
    DB.SessionLocal = sessionmaker(bind=DB.engine)

    if settings.auto_migrate_on_startup:
        try:
            apply_schema(DB.engine)
        except SQLAlchemyError as exc:
            raise RuntimeError("Failed to apply schema migrations") from exc


def get_db_session() -> Generator:
    if DB.SessionLocal is None:
        raise RuntimeError("Database not initialized")
    db = DB.SessionLocal()
    try:
        yield db
    finally:
        db.close()
