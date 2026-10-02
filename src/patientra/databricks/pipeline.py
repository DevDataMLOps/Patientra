"""Bounded batch orchestration; Spark publication is separate from validation.

All patient data stays in the protected run directory. Failed runs never receive
a release manifest. Existing runs cannot be overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from patientra.analytics.readmission import build_analytics
from patientra.features.gold import GoldConfig, build_gold
from patientra.ingestion.ingest import ingest_csv
from patientra.matching.identity import resolve_identities
from patientra.ml.readmission import run_experiment
from patientra.transformations.silver import SilverConfig, build_silver
from patientra.validation.release import validate_release

INPUT_NAMES = ("patients.csv", "admissions.csv", "lab_results.csv")
RULE_VERSION = "databricks-batch-v1"
MAX_INPUT_BYTES = 50 * 1024 * 1024


class PipelineError(RuntimeError):
    """An orchestration or integrity gate failed."""


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def artifact_inventory(root):
    return {p.relative_to(root).as_posix(): sha256(p)
            for p in sorted(root.rglob("*")) if p.is_file()
            and p != root / "release_manifest.json"}


def verify_run(root):
    """Recheck every protected artifact before any Delta or release publication."""
    root = Path(root)
    manifest = json.loads((root / "release_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "VALIDATED_DEMONSTRATION":
        raise PipelineError("Run is not validated.")
    if manifest.get("artifact_sha256") != artifact_inventory(root):
        raise PipelineError("Run artifacts changed after validation.")
    validation = json.loads((root / "validation/release_validation.json").read_text())
    ml = json.loads((root / "ml/readmission_ml.json").read_text())
    if (validation.get("status") != "PASS" or len(validation.get("checks", [])) != 13
            or any(c.get("status") != "PASS" for c in validation["checks"])):
        raise PipelineError("Release validation did not pass all checks.")
    if (ml.get("governance", {}).get("release_status") != "DEMONSTRATION_ONLY"
            or set(ml.get("technical_checks", {}).values()) != {"PASS"}
            or ml.get("split", {}).get("shared_master_patients") != 0):
        raise PipelineError("ML validation did not pass.")
    return manifest


def run_pipeline(raw_dir, run_dir, repository_root, master_key, observation_end,
                 *, cutoff=date(2025, 1, 1), slash_date_order="reject",
                 numeric_sex_codes=(), source_commit, run_id=None,
                 review_decisions=None):
    """Execute Bronze -> Silver -> identity -> Gold -> analytics -> validation -> ML.

    This preserves the existing case-study, driver-memory algorithms rather than
    silently replacing them with different distributed matching or label semantics.
    Source delivery must already satisfy the official combined LG/RS schema.
    """
    raw, root, repository = map(lambda p: Path(p).resolve(),
                                (raw_dir, run_dir, repository_root))
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise PipelineError("A full source commit SHA is required.")
    actual_id = str(uuid.UUID(run_id)) if run_id else str(uuid.uuid4())
    if not isinstance(master_key, bytes) or len(master_key) < 32:
        raise PipelineError("A protected 32-byte or longer matching key is required.")
    if observation_end <= cutoff:
        raise PipelineError("Observation end must follow the fixed ML cutoff.")
    sources = {name: raw / name for name in INPUT_NAMES}
    if any(not path.is_file() for path in sources.values()):
        raise PipelineError("The three canonical input files are required.")
    if sum(path.stat().st_size for path in sources.values()) > MAX_INPUT_BYTES:
        raise PipelineError("Delivery exceeds the bounded batch size limit.")
    if root.exists():
        raise PipelineError("Run directory exists; choose a new run ID.")
    if root == raw or raw in root.parents or root in raw.parents:
        raise PipelineError("Raw and run directories must be separate trees.")
    source_hashes = {name: sha256(path) for name, path in sources.items()}
    root.mkdir(parents=True)
    snapshots = root / "input"
    snapshots.mkdir()
    for name, path in sources.items():
        shutil.copyfile(path, snapshots / name)
    if source_hashes != {name: sha256(snapshots / name) for name in INPUT_NAMES}:
        raise PipelineError("Source delivery changed during snapshotting.")
    reviews = None
    if review_decisions is not None:
        reviews = snapshots / "review_decisions.csv"
        shutil.copyfile(review_decisions, reviews)
    bronze = {}
    for name in INPUT_NAMES:
        result = ingest_csv(snapshots / name, "delivery", root / "bronze",
                            root / "quarantine/bronze", run_id=actual_id)
        bronze[name] = Path(result.bronze_path)
    build_silver(bronze["patients.csv"], bronze["admissions.csv"],
                 bronze["lab_results.csv"], root / "silver", root / "quarantine/silver",
                 config=SilverConfig(slash_date_order, tuple(numeric_sex_codes)),
                 run_id=actual_id)
    resolve_identities(root / "silver/patients.silver.csv", root / "identity",
                       master_key, review_decisions=reviews, run_id=actual_id)
    build_gold(root / "silver/patients.silver.csv", root / "silver/admissions.silver.csv",
               root / "silver/lab_results.silver.csv", root / "identity/patient_master.csv",
               root / "gold", GoldConfig(observation_end), run_id=actual_id)
    build_analytics(root / "gold/readmission_features.csv", root / "analytics",
                    run_id=actual_id)
    validation = validate_release(repository, root / "gold/readmission_features.csv",
                                  root / "gold/readmission_feature_audit.json",
                                  root / "analytics/readmission_analytics.json",
                                  root / "analytics/readmission_breakdowns.csv",
                                  root / "analytics/readmission_analytics_audit.json",
                                  root / "validation/release_validation.json")
    run_experiment(root / "gold/readmission_features.csv", root / "identity/patient_master.csv",
                   root / "identity/identity_audit.json", root / "gold/readmission_feature_audit.json",
                   cutoff, root / "ml/readmission_ml.json")
    if source_hashes != {name: sha256(path) for name, path in sources.items()}:
        raise PipelineError("Source delivery changed during execution.")
    manifest = {"rule_version": RULE_VERSION, "run_id": actual_id,
                "source_commit": source_commit, "status": "VALIDATED_DEMONSTRATION",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "observation_end": observation_end.isoformat(), "cutoff": cutoff.isoformat(),
                "source_sha256": source_hashes, "validation_checks_passed": validation.checks_passed,
                "artifact_sha256": artifact_inventory(root),
                "clinical_use": False, "individual_predictions_exported": False}
    write_json(root / "release_manifest.json", manifest)
    verify_run(root)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Execute a validated PATIENTRA batch.")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--observation-end", type=date.fromisoformat, required=True)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2025, 1, 1))
    args = parser.parse_args(argv)
    key = os.environ.get("PATIENTRA_MATCH_KEY", "").encode()
    try:
        report = run_pipeline(args.raw_dir, args.run_dir, args.repository_root, key,
                              args.observation_end, cutoff=args.cutoff,
                              source_commit=args.source_commit)
    except Exception:
        # No patient values, sensitive paths, or secret values in job logs.
        print("PATIENTRA batch failed; inspect protected run evidence.")
        return 1
    print(json.dumps({"run_id": report["run_id"], "status": report["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
