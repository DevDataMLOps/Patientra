import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from patientra.databricks.pipeline import PipelineError, run_pipeline, verify_run
from patientra.databricks.delta import identifier, snapshot_plan, publication_error_details

REPOSITORY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("demo", REPOSITORY / "scripts/generate_databricks_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture
def delivery(tmp_path):
    return demo.generate(tmp_path / "raw")


def execute(delivery, output):
    return run_pipeline(delivery, output, REPOSITORY, b"synthetic-test-key-not-a-secret-0000",
                        date(2025, 12, 31), source_commit="a" * 40)


def test_complete_pipeline_and_snapshot_plan_preserve_private_boundary(delivery, tmp_path):
    root = tmp_path / "run"
    report = execute(delivery, root)
    assert verify_run(root) == report
    assert report["validation_checks_passed"] == 13
    ml = json.loads((root / "ml/readmission_ml.json").read_text())
    assert ml["split"]["shared_master_patients"] == 0
    assert ml["split"]["train_readmissions"] == ml["split"]["test_readmissions"] == 20
    assert ml["governance"]["release_status"] == "DEMONSTRATION_ONLY"
    assert "FICTIONAL-" not in json.dumps(report)
    assert "FICTIONAL-" not in json.dumps(ml)
    assert not any(p.suffix in {"pkl", ".joblib"} for p in root.rglob("*"))
    plan = snapshot_plan(root, "patientra", report["run_id"])
    assert any(".bronze." in name for _, name in plan)
    assert any(".silver.patient_master_" in name for _, name in plan)
    assert any(".gold.readmission_features_" in name for _, name in plan)
    assert len({name for _, name in plan}) == len(plan)
    with pytest.raises(PipelineError, match="exists"):
        execute(delivery, root)
    (root / "gold/readmission_features.csv").write_text("changed")
    with pytest.raises(PipelineError, match="changed"):
        verify_run(root)


def test_missing_ml_classes_does_not_create_release(delivery, tmp_path):
    target = tmp_path / "failed"
    with pytest.raises(Exception, match="11"):
        run_pipeline(delivery, target, REPOSITORY, b"x" * 32, date(2025, 12, 31),
                     source_commit="a" * 40, cutoff=date(2024, 1, 1))
    assert not (target / "release_manifest.json").exists()


def test_invalid_inputs_fail_before_writing(delivery, tmp_path):
    target = tmp_path / "run"
    with pytest.raises(PipelineError, match="SHA"):
        run_pipeline(delivery, target, REPOSITORY, b"x" * 32, date(2025, 12, 31),
                     source_commit="main")
    assert not target.exists()
    with pytest.raises(PipelineError, match="separate"):
        execute(delivery, delivery / "run")
    for invalid in ("patientra; DROP CATALOG x", "Patientra", "../data", ""):
        with pytest.raises(PipelineError):
            identifier(invalid)


def test_publication_diagnostics_keep_classification_without_sensitive_payload():
    class SparkFailure(Exception):
        def getCondition(self):
            return "INSUFFICIENT_PERMISSIONS"

        def getSqlState(self):
            return "42501"

        def getMessageParameters(self):
            raise AssertionError("Sensitive parameters must not be read")

    error = SparkFailure("patient name, secret key, raw result, and /protected/path")
    details = publication_error_details(error, "delta_publication", "cee97894-2a8d-4763-b5d9-214eebb176b3")
    assert details == {"stage": "delta_publication", "run_id": "cee97894-2a8d-4763-b5d9-214eebb176b3",
                       "exception_type": "SparkFailure", "error_condition": "INSUFFICIENT_PERMISSIONS",
                       "sql_state": "42501"}
    assert "patient" not in json.dumps(details)
    assert str(error) not in json.dumps(details)


def test_publication_diagnostics_fallback_and_untrusted_metadata():
    class LegacyFailure(Exception):
        def getCondition(self):
            raise RuntimeError("method unavailable")

        def getErrorClass(self):
            return "TABLE_OR_VIEW_NOT_FOUND"

        def getSqlState(self):
            return "secret-value"

    run_id = "cee97894-2a8d-4763-b5d9-214eebb176b3"
    details = publication_error_details(LegacyFailure("private"), "mlflow", run_id)
    assert details["error_condition"] == "TABLE_OR_VIEW_NOT_FOUND"
    assert "sql_state" not in details
    class UnsafeFailure(Exception):
        def getCondition(self):
            return "PRIVATE PATIENT\n" + "X" * 200

    assert "error_condition" not in publication_error_details(UnsafeFailure(), "mlflow", run_id)
    with pytest.raises(ValueError):
        publication_error_details(RuntimeError(), "private-path", run_id)
    with pytest.raises(ValueError):
        publication_error_details(RuntimeError(), "mlflow", "patient-name")
