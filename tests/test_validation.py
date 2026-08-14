

class TestSchemaResolution:
    """The schema must be found once installed, and never fail open.

    An installed ReceiptGate resolved parents[2] to the site-packages parent
    and found nothing, and validate_json_schema returned [] on a missing file.
    Every phase rule in receipt.rules.md was therefore unenforced in
    deployment while passing in a source checkout.
    """

    def test_schema_resolves_to_a_real_file(self):
        from receiptgate.validation_v1 import _schema_path

        assert _schema_path().is_file(), f"schema not found at {_schema_path()}"

    def test_packaged_schema_is_preferred(self):
        from pathlib import Path
        import receiptgate
        from receiptgate.validation_v1 import _schema_path

        packaged = Path(receiptgate.__file__).resolve().parent / "schema" / "receipt.schema.v1.json"
        if packaged.is_file():
            assert _schema_path() == packaged

    def test_override_is_honoured(self, monkeypatch, tmp_path):
        from receiptgate.validation_v1 import _schema_path

        monkeypatch.setenv("RECEIPTGATE_SCHEMA_DIR", str(tmp_path))
        assert _schema_path() == tmp_path / "receipt.schema.v1.json"

    def test_missing_schema_raises_rather_than_passing_everything(self, monkeypatch, tmp_path):
        """Fail loudly: a validator that cannot find its rules is misconfigured."""
        import pytest
        from receiptgate.validation_v1 import validate_json_schema

        monkeypatch.setenv("RECEIPTGATE_SCHEMA_DIR", str(tmp_path / "nowhere"))
        with pytest.raises(RuntimeError, match="Receipt schema not found"):
            validate_json_schema({"phase": "accepted"})


class TestPhaseRulesAreEnforced:
    """Spot-check that the conditional rules actually reject, not just parse."""

    def _accepted(self, **overrides):
        base = {
            "schema_version": "1.0", "tenant_id": "default", "receipt_id": "r1",
            "task_id": "t1", "parent_task_id": "NA", "caused_by_receipt_id": "NA",
            "dedupe_key": "NA", "attempt": 0, "from_principal": "p", "for_principal": "p",
            "source_system": "test", "recipient_ai": "a", "trust_domain": "d",
            "phase": "accepted", "status": "NA", "realtime": False, "task_type": "t",
            "task_summary": "s", "task_body": "b", "inputs": {},
            "expected_outcome_kind": "response_text", "expected_artifact_mime": "NA",
            "outcome_kind": "NA", "outcome_text": "NA", "artifact_location": "NA",
            "artifact_pointer": "NA", "artifact_checksum": "NA", "artifact_size_bytes": 0,
            "artifact_mime": "NA", "escalation_class": "NA", "escalation_reason": "NA",
            "escalation_to": "NA", "retry_requested": False, "body": {},
            "created_at": "2026-08-14T12:00:00Z", "stored_at": None,
            "started_at": None, "completed_at": None, "read_at": None,
            "archived_at": None, "metadata": {},
        }
        base.update(overrides)
        return base

    def test_valid_accepted_passes(self):
        from receiptgate.validation_v1 import validate_json_schema

        assert validate_json_schema(self._accepted()) == []

    def test_accepted_with_terminal_status_is_rejected(self):
        from receiptgate.validation_v1 import validate_json_schema

        assert validate_json_schema(self._accepted(status="success"))

    def test_accepted_with_completed_at_is_rejected(self):
        from receiptgate.validation_v1 import validate_json_schema

        assert validate_json_schema(self._accepted(completed_at="2026-08-14T12:00:00Z"))

    def test_accepted_claiming_an_artifact_is_rejected(self):
        from receiptgate.validation_v1 import validate_json_schema

        assert validate_json_schema(self._accepted(artifact_pointer="depotgate://x"))
