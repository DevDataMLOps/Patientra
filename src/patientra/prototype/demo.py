"""Run a fresh synthetic delivery and export a tightly typed demonstration."""
import csv
import hashlib
import importlib.util
import json
import secrets
import subprocess
from datetime import date
from pathlib import Path

from patientra.api.bundle import export_bundle
from patientra.databricks.pipeline import run_pipeline, verify_run
from patientra.prototype.models import DemoEvidence
from patientra.serving.store import publish


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def synthetic_delivery(repository, output):
    spec = importlib.util.spec_from_file_location("patientra_demo_input", Path(repository) / "scripts/generate_databricks_demo.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    output = generator.generate(output)
    # A fictional cross-hospital ambiguous pair: never auto-accept it.
    path = output / "patients.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, patients = reader.fieldnames, list(reader)
    for row in patients[-2:]:
        row.update(first_name="FICTIONALDEMO", last_name="IDENTITYREVIEW", sex="F")
    invalid = dict(patients[0], patient_id="LG-999999", date_of_birth="not-a-date")
    _write_csv(path, patients + [invalid], fields)
    for dataset, changes in (("admissions", {"admission_id": "FICTIONAL-BAD-ADM", "patient_id": "LG-999999"}),
                             ("lab_results", {"lab_id": "FICTIONAL-BAD-LAB", "result_value": "not-a-number"})):
        path = output / f"{dataset}.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        _write_csv(path, rows + [dict(rows[0], **changes)], fields)
    return output


def prepare_demo(repository, root):
    repository, root = Path(repository).resolve(), Path(root).resolve()
    if root.exists():
        raise ValueError("Use a new demonstration directory; existing runs are preserved")
    source_commit = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    root.mkdir(parents=True)
    raw = synthetic_delivery(repository, root / "raw")
    run = root / "run"
    manifest = run_pipeline(raw, run, repository, secrets.token_bytes(32), date(2025, 12, 31),
                            source_commit=source_commit)
    verify_run(run)
    database = root / "serving.sqlite"
    publish(run / "analytics/readmission_analytics.json", run / "analytics/readmission_breakdowns.csv",
            run / "analytics/readmission_analytics_audit.json", run / "validation/release_validation.json", database)
    bundle = root / "approved-aggregates.json"
    bundle_digest = export_bundle(database, bundle, identity_audit=run / "identity/identity_audit.json",
                                  patient_master=run / "identity/patient_master.csv",
                                  gold_audit=run / "gold/readmission_feature_audit.json",
                                  gold=run / "gold/readmission_features.csv", validation=run / "validation/release_validation.json")
    silver = _read(run / "silver/silver_audit.json")
    identity = _read(run / "identity/identity_audit.json")
    gate = _read(run / "validation/release_validation.json")
    ml = _read(run / "ml/readmission_ml.json")
    # Project allowlisted scalar aggregates; never export a full audit or source record.
    split_fields = ("cutoff_date", "label_embargo_days", "shared_master_patients", "train_admissions",
                    "test_admissions", "train_readmissions", "test_readmissions")
    metric_fields = ("roc_auc", "average_precision", "brier_score", "balanced_accuracy_at_0_5", "log_loss")
    payload = {"contract": "patientra-synthetic-prototype-v1", "data_mode": "SYNTHETIC_ONLY",
               "run_id": manifest["run_id"], "source_commit": source_commit, "created_at_utc": manifest["created_at_utc"],
               "bundle_sha256": bundle_digest, "bronze": silver["source_rows"], "silver": silver["silver_rows"],
               "quarantine": silver["quarantine_rows"], "gold_rows": ml["cohort"]["gold_rows"],
               "master_patients": identity["unique_master_patients"],
               "unresolved_identity_reviews": ml["cohort"]["unresolved_identity_reviews"],
               "validation_checks": [{"check": c["check"], "status": c["status"]} for c in gate["checks"]],
               "ml": {key: ml["governance"][key] for key in ("release_status", "clinical_accuracy", "model_artifact_exported", "individual_predictions_exported")}}
    payload["ml"].update(split={**{key: ml["split"][key] for key in split_fields},
                                "pending_identity_excluded_admissions": ml["cohort"]["pending_identity_excluded_admissions"]},
                         technical_checks=[{"check": key, "status": value} for key, value in ml["technical_checks"].items()])
    for model in ("logistic_regression", "training_prevalence_baseline"):
        payload["ml"][model] = {key: ml["evaluation"][model][key] for key in metric_fields}
    evidence = DemoEvidence.model_validate_json(json.dumps(payload))
    evidence_path = root / "prototype-evidence.json"
    evidence_path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"bundle_path": str(bundle), "bundle_sha256": bundle_digest,
            "evidence_path": str(evidence_path), "evidence_sha256": sha(evidence_path), "run_id": manifest["run_id"]}
