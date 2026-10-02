"""Phase 10 discharge-time readmission experiment, with aggregate-only output.

Models and individual predictions exist only in process memory. Protected source
identities are used for exclusion and splitting, never as model features/output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import tempfile
import warnings
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

from patientra.analytics.readmission import _read_gold, _validate_rows
from patientra.matching.identity import MASTER_FIELDS

RULE_VERSION = "phase10-readmission-v1"
SEED = 42
NUMERIC_FEATURES = (
    "age_at_admit", "length_of_stay_days", "prior_completed_admission_count",
    "prior_admission_30d_count", "prior_admission_365d_count",
    "prior_same_diagnosis_group_count", "prior_distinct_hospital_count",
    "days_since_prior_discharge",
)
CATEGORICAL_FEATURES = ("hospital", "sex", "diagnosis_group", "discharge_status")
FEATURES = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
MINIMUM_CELL = 11


class MLError(RuntimeError):
    """A sanitized error: source values and identifiers must never be printed."""


def _require(condition, message):
    if not condition:
        raise MLError(message)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cohort(gold, patient_master, identity_audit, gold_audit):
    """Reconcile private master lineage, then exclude all pending identities."""
    _, rows = _read_gold(gold)
    _validate_rows(rows)
    with Path(patient_master).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        _require(reader.fieldnames == list(MASTER_FIELDS), "Master schema mismatch.")
        master = list(reader)
    audit = json.loads(Path(identity_audit).read_text(encoding="utf-8"))
    gold_lineage = json.loads(Path(gold_audit).read_text(encoding="utf-8"))
    _require(gold_lineage.get("input_sha256", {}).get("patient_master") == _hash(patient_master)
             and gold_lineage.get("gold_rows") == len(rows)
             and gold_lineage.get("label_status_counts") == dict(Counter(r["label_status"] for r in rows))
             and gold_lineage.get("observation_end_date") == rows[0]["observation_end_date"]
             and gold_lineage.get("rule_version") == "phase4-gold-v1",
             "Gold audit lineage failed.")
    statuses = {"AUTO_MATCHED", "HUMAN_ACCEPTED", "UNMATCHED", "REVIEW_PENDING"}
    _require(all(set(r) == set(MASTER_FIELDS) and all(v is not None for v in r.values())
                 and r["master_patient_id"] and r["patient_id"]
                 and r["link_status"] in statuses for r in master), "Invalid master rows.")
    _require(len({(r["source_system"], r["patient_id"]) for r in master}) == len(master),
             "Duplicate master source records.")
    known = {r["master_patient_id"] for r in master}
    pending = {r["master_patient_id"] for r in master if r["link_status"] == "REVIEW_PENDING"}
    _require(len(master) == audit.get("master_patient_rows")
             and len(known) == audit.get("unique_master_patients")
             and sum(r["link_status"] == "REVIEW_PENDING" for r in master)
             == audit.get("review_pending_source_rows")
             and audit.get("one_to_one_constraint_passed") is True,
             "Identity audit reconciliation failed.")
    _require(all(r["master_patient_id"] in known for r in rows), "Gold/master mismatch.")
    unresolved = sum(audit.get("review_status_counts", {}).get(s, 0) for s in ("PENDING", "ABSTAIN"))
    _require(isinstance(unresolved, int) and unresolved >= 0
             and len(pending) == 2 * unresolved, "Pending review reconciliation failed.")
    eligible = [r for r in rows if r["label_status"] in {"labeled_positive", "labeled_negative"}]
    usable = [r for r in eligible if r["master_patient_id"] not in pending]
    complete = [r for r in usable if date.fromisoformat(r["discharge_date"]) + timedelta(days=30)
                <= date.fromisoformat(r["observation_end_date"])]
    _require(all(r["feature_rule_version"] == "phase4-gold-v1" for r in rows),
             "Unsupported Gold feature version.")
    return rows, complete, {
        "gold_rows": len(rows), "eligible_admissions": len(eligible),
        "observed_readmissions": sum(int(r["readmitted_30d"]) for r in eligible),
        "excluded_label_rows": len(rows) - len(eligible),
        "pending_identity_excluded_admissions": len(eligible) - len(usable),
        "incomplete_followup_positive_rows_excluded": len(usable) - len(complete),
        "unresolved_identity_reviews": unresolved,
    }


def temporal_split(rows, cutoff):
    """Fixed date; 30-day label embargo; future holdout excludes train patients."""
    train = [r for r in rows if date.fromisoformat(r["discharge_date"]) + timedelta(days=30) < cutoff]
    train_ids = {r["master_patient_id"] for r in train}
    future = [r for r in rows if date.fromisoformat(r["admit_date"]) >= cutoff]
    test = [r for r in future if r["master_patient_id"] not in train_ids]
    for cohort in (train, test):
        counts = Counter(r["readmitted_30d"] for r in cohort)
        _require(counts["0"] >= MINIMUM_CELL and counts["1"] >= MINIMUM_CELL,
                 "Each split requires at least 11 admissions per outcome class.")
    _require(not train_ids.intersection(r["master_patient_id"] for r in test),
             "Patient overlap detected.")
    return train, test, {
        "cutoff_date": cutoff.isoformat(), "label_embargo_days": 30,
        "train_admissions": len(train), "test_admissions": len(test),
        "train_master_patients": len(train_ids),
        "test_master_patients": len({r["master_patient_id"] for r in test}),
        "shared_master_patients": 0,
        "future_returning_patient_rows_excluded": len(future) - len(test),
        "boundary_rows_excluded": len(rows) - len(train) - len(future),
        "train_readmissions": sum(int(r["readmitted_30d"]) for r in train),
        "test_readmissions": sum(int(r["readmitted_30d"]) for r in test),
    }


def feature_matrix(rows):
    import numpy as np
    result = []
    for row in rows:
        numeric = []
        for feature in NUMERIC_FEATURES:
            value = row[feature]
            _require(value != "" or feature == "days_since_prior_discharge", "Missing required feature.")
            number = float(value) if value else np.nan
            _require(not value or (math.isfinite(number) and number >= 0), "Invalid numeric feature.")
            numeric.append(number)
        for feature in CATEGORICAL_FEATURES:
            _require(bool(row[feature]), "Missing categorical feature.")
        result.append([*numeric, *(row[f] for f in CATEGORICAL_FEATURES)])
    return np.asarray(result, dtype=object)


def build_model():
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    numeric = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
    ])
    preprocessing = ColumnTransformer([
        ("numeric", numeric, list(range(len(NUMERIC_FEATURES)))),
        ("category", OneHotEncoder(handle_unknown="ignore", min_frequency=MINIMUM_CELL),
         list(range(len(NUMERIC_FEATURES), len(FEATURES)))),
    ])
    return Pipeline([
        ("preprocess", preprocessing),
        ("model", LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs", random_state=SEED)),
    ])


def metrics(labels, probabilities):
    import numpy as np
    from sklearn.metrics import (average_precision_score, balanced_accuracy_score,
                                 brier_score_loss, confusion_matrix, log_loss, roc_auc_score)
    _require(np.isfinite(probabilities).all() and ((probabilities >= 0) & (probabilities <= 1)).all(),
             "Invalid model probabilities.")
    predicted = (probabilities >= 0.5).astype(int)
    cells = confusion_matrix(labels, predicted, labels=[0, 1]).ravel().tolist()
    suppressed = any(cell < MINIMUM_CELL for cell in cells)
    return {
        "roc_auc": round(float(roc_auc_score(labels, probabilities)), 6),
        "average_precision": round(float(average_precision_score(labels, probabilities)), 6),
        "brier_score": round(float(brier_score_loss(labels, probabilities)), 6),
        "log_loss": round(float(log_loss(labels, probabilities, labels=[0, 1])), 6),
        "balanced_accuracy_at_0_5": round(float(balanced_accuracy_score(labels, predicted)), 6),
        "confusion_matrix_at_0_5": None if suppressed else dict(zip(("tn", "fp", "fn", "tp"), cells)),
        "confusion_matrix_suppressed": suppressed,
    }


def run_experiment(gold, patient_master, identity_audit, gold_audit, cutoff, output, *, overwrite=False):
    from sklearn.dummy import DummyClassifier
    from sklearn.exceptions import ConvergenceWarning
    import numpy as np
    output = Path(output).resolve()
    sources = {"gold": Path(gold).resolve(), "patient_master": Path(patient_master).resolve(),
               "identity_audit": Path(identity_audit).resolve(), "gold_audit": Path(gold_audit).resolve()}
    _require(output not in sources.values(), "Output cannot replace an input.")
    _require(not output.exists() or overwrite, "Output exists; use --overwrite for an intentional rerun.")
    hashes = {key: _hash(path) for key, path in sources.items()}
    _, rows, cohort = load_cohort(gold, patient_master, identity_audit, gold_audit)
    train, test, split = temporal_split(rows, cutoff)
    # Combine flow exclusions so a tiny incomplete-followup count cannot be
    # recovered by subtracting the other published cohort counts.
    split["time_boundary_or_incomplete_followup_rows_excluded"] = (
        split.pop("boundary_rows_excluded") + cohort.pop("incomplete_followup_positive_rows_excluded")
    )
    x_train, x_test = feature_matrix(train), feature_matrix(test)
    y_train = np.array([int(r["readmitted_30d"]) for r in train])
    y_test = np.array([int(r["readmitted_30d"]) for r in test])
    model = build_model()
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(x_train, y_train)
    baseline = DummyClassifier(strategy="prior").fit(x_train, y_train)
    learned = metrics(y_test, model.predict_proba(x_test)[:, 1])
    reference = metrics(y_test, baseline.predict_proba(x_test)[:, 1])
    _require(hashes == {key: _hash(path) for key, path in sources.items()}, "Inputs changed during experiment.")
    report = {
        "rule_version": RULE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_sha256": hashes,
        "implementation_sha256": _hash(Path(__file__)),
        "runtime": {"python": platform.python_version(), **{name: version(name) for name in
                    ("scikit-learn", "numpy", "scipy", "joblib", "threadpoolctl")}},
        "prediction_time": "index discharge; diagnosis/discharge fields assumed available",
        "cohort": cohort, "split": split,
        "features": {"numeric": list(NUMERIC_FEATURES), "categorical": list(CATEGORICAL_FEATURES),
                     "excluded": ["identifiers", "dates", "labels", "label_status", "observation_end_date", "laboratory_summaries"]},
        "configuration": {"seed": SEED, "model": "logistic_regression", "C": 1.0,
                          "max_iter": 2000, "solver": "lbfgs", "threshold": 0.5,
                          "hyperparameter_search": False, "minimum_cell_size": MINIMUM_CELL},
        "evaluation": {"logistic_regression": learned, "training_prevalence_baseline": reference},
        "technical_checks": {"input_validation": "PASS", "identity_exclusion": "PASS",
                             "patient_disjoint_split": "PASS", "training_labels_matured": "PASS",
                             "train_only_preprocessing": "PASS", "convergence": "PASS",
                             "input_immutability": "PASS", "aggregate_only_output": "PASS"},
        "governance": {"release_status": "DEMONSTRATION_ONLY", "clinical_accuracy": "NOT_ASSESSED",
                       "public_ml_deployment": False, "individual_predictions_exported": False,
                       "model_artifact_exported": False, "identity_reviews_resolved_by_ml": False,
                       "limitations": ["synthetic case-study data", "provisional identity resolution",
                                       "new-patient temporal holdout only", "no external or prospective validation",
                                       "no clinical threshold selection", "no subgroup fairness assessment",
                                       "confidence intervals not estimated"]},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local demonstration readmission ML; aggregate evidence only.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--patient-master", type=Path, required=True)
    parser.add_argument("--identity-audit", type=Path, required=True)
    parser.add_argument("--gold-audit", type=Path, required=True)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--output", type=Path, default=Path("outputs/phase10/readmission_ml.json"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_experiment(args.gold, args.patient_master, args.identity_audit, args.gold_audit,
                                args.cutoff, args.output, overwrite=args.overwrite)
    except ImportError:
        print("ML dependencies unavailable. Install patientra[ml].")
        return 1
    except Exception:
        # Do not leak identifiers, paths, CSV fragments or estimator input values.
        print("ML experiment failed validation or execution; no new evidence published.")
        return 1
    print(json.dumps({"rule_version": report["rule_version"], "release_status": "DEMONSTRATION_ONLY",
                      "train_admissions": report["split"]["train_admissions"],
                      "test_admissions": report["split"]["test_admissions"],
                      "unresolved_identity_reviews": report["cohort"]["unresolved_identity_reviews"]}))
    return 0
