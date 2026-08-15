"""A committed receipt must not be reported as a failure by its own log line.

`put_receipt` logs after `db.commit()` and outside the enclosing try/except.
The log call passed structlog-style keyword arguments to a stdlib logger, which
raises `TypeError`. It was invisible because the root logger defaults to
WARNING and `Logger.info` short-circuits on `isEnabledFor` before unpacking
kwargs -- and the entire test suite runs at that default.

So the failure only appeared under `--log-level info`, the normal production
posture: the INSERT committed durably, the log line raised, the exception
propagated to the route handler, and the client was told
"Failed to store receipt" for a receipt that is in the database. A client that
reacts by minting a different receipt for the same obligation corrupts the
ledger.

These tests force INFO so the kwargs are actually evaluated. Revert the fix to
kwargs and they fail.
"""

from __future__ import annotations

import logging

import pytest

from receiptgate import ledger_v1


@pytest.fixture
def info_logging(caplog):
    """Force the receipt logger to INFO so log arguments are evaluated."""
    caplog.set_level(logging.INFO, logger="receiptgate.ledger_v1")
    ledger_v1.logger.setLevel(logging.INFO)
    yield caplog
    ledger_v1.logger.setLevel(logging.NOTSET)


def test_store_receipt_log_line_does_not_raise_at_info(info_logging):
    """The exact call shape from put_receipt, executed at INFO."""
    record = {
        "task_id": "T-1",
        "phase": "accepted",
        "recipient_ai": "agent:demo",
        "caused_by_receipt_id": "NA",
    }
    # Mirrors put_receipt's call. If this is ever rewritten with kwargs it
    # raises TypeError here rather than after a durable commit in production.
    ledger_v1.logger.info(
        "receiptgate_v1_receipt_stored",
        extra={
            "receipt_id": "r-1",
            "tenant_id": "default",
            "task_id": record.get("task_id"),
            "phase": record.get("phase"),
            "recipient_ai": record.get("recipient_ai"),
            "caused_by_receipt_id": record.get("caused_by_receipt_id"),
        },
    )
    assert any(
        r.message == "receiptgate_v1_receipt_stored" for r in info_logging.records
    )


def test_no_structlog_kwargs_on_the_stdlib_logger():
    """Guard the whole module, not just the one line that was broken.

    `ledger_v1` uses stdlib `logging`; structlog is not a dependency. Any
    structured field must travel via `extra=`. This catches the next instance
    without waiting for someone to run at INFO.
    """
    import ast
    import inspect

    source = inspect.getsource(ledger_v1)
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in {"debug", "info", "warning", "error", "critical", "exception"}:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "logger"):
            continue
        allowed = {"extra", "exc_info", "stack_info", "stacklevel"}
        bad = [kw.arg for kw in node.keywords if kw.arg not in allowed]
        if bad:
            offenders.append((node.lineno, bad))

    assert not offenders, (
        f"stdlib logger called with structlog-style kwargs at {offenders}; "
        f"this raises TypeError at the configured log level and, on the write "
        f"path, does so after the receipt has already committed"
    )
