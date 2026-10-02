import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from patientra.features.gold import GOLD_FIELDS
from patientra.matching.identity import MASTER_FIELDS
from patientra.ml.readmission import (
    FEATURES, MLError, _hash, build_model, feature_matrix, load_cohort,
    main, metrics, run_experiment, temporal_split,
)


def row(number, *, future=False, positive=False):
    result = dict.fromkeys(GOLD_FIELDS, "")
    result.update({
        "admission_id": f"PRIVATE-ADMISSION-{number}",
        "master_patient_id": f"PRIVATE-PATIENT-{number}",
        "hospital": "Lakeside General", "sex": "F", "diagnosis_group": "I50",
        "admit_date": "2025-06-01" if future else "2024-06-01",
        "discharge_date": "2025-06-05" if future else "2024-06-05",
        "discharge_status": "home", "length_of_stay_days": "4",
        "age_at_admit": "60", "prior_completed_admission_count": "0",
        "prior_admission_30d_count": "0", "prior_admission_365d_count": "0",
        "prior_same_diagnosis_group_count": "0", "prior_distinct_hospital_count": "0",
        "readmitted_30d": "1" if positive else "0",
        "label_status": "labeled_positive" if positive else "labeled_negative",
        "observation_end_date": "2025-12-31", "feature_rule_version": "phase4-gold-v1",
    })
    return result


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def inputs(tmp_path):
    rows = [row(n, future=n >= 80, positive=n % 4 == 0) for n in range(160)]
    # Pending candidates appear in each period and must both be removed.
    masters = [{"master_patient_id": r["master_patient_id"], "patient_id": f"PRIVATE-SOURCE-{n}",
                "source_system": "LG", "link_status": "REVIEW_PENDING" if n in (0, 80) else "UNMATCHED",
                "match_case_id": "PRIVATE-CASE" if n in (0, 80) else "", "rule_version": "phase3-identity-v1"}
               for n, r in enumerate(rows)]
    gold, master = tmp_path / "gold.csv", tmp_path / "master.csv"
    write_csv(gold, GOLD_FIELDS, rows)
    write_csv(master, MASTER_FIELDS, masters)
    identity, audit = tmp_path / "identity.json", tmp_path / "gold-audit.json"
    identity.write_text(json.dumps({"master_patient_rows": 160, "unique_master_patients": 160,
                                   "review_pending_source_rows": 2, "one_to_one_constraint_passed": True,
                                   "review_status_counts": {"PENDING": 1}}))
    audit.write_text(json.dumps({"input_sha256": {"patient_master": _hash(master)}, "gold_rows": 160,
                                "label_status_counts": dict(Counter(r["label_status"] for r in rows)),
                                "observation_end_date": "2025-12-31", "rule_version": "phase4-gold-v1"}))
    return gold, master, identity, audit


def test_pending_exclusion_and_master_lineage_fail_closed(inputs):
    _, usable, counts = load_cohort(*inputs)
    assert len(usable) == 158
    assert not {"PRIVATE-PATIENT-0", "PRIVATE-PATIENT-80"}.intersection(r["master_patient_id"] for r in usable)
    assert counts["unresolved_identity_reviews"] == 1
    inputs[1].write_text(inputs[1].read_text().replace("REVIEW_PENDING", "UNMATCHED"))
    with pytest.raises(MLError, match="lineage"):
        load_cohort(*inputs)


def test_temporal_patient_split_embargo_and_tiny_class_rejection():
    rows = [row(n, future=n >= 40, positive=n % 2 == 0) for n in range(80)]
    returning = row(99, future=True, positive=True)
    returning["master_patient_id"] = rows[0]["master_patient_id"]
    embargo = row(100)
    embargo.update(admit_date="2024-12-01", discharge_date="2024-12-05")
    train, test, split = temporal_split([*rows, returning, embargo], date(2025, 1, 1))
    assert len(train) == len(test) == 40
    assert split["boundary_rows_excluded"] == split["future_returning_patient_rows_excluded"] == 1
    assert not {r["master_patient_id"] for r in train}.intersection(r["master_patient_id"] for r in test)
    with pytest.raises(MLError, match="11"):
        temporal_split(rows[:12], date(2025, 1, 1))


def test_preprocessing_is_train_only_and_future_unknown_categories_work():
    train = [row(n, positive=n % 2 == 0) for n in range(40)]
    future = [row(100, future=True)]
    future[0].update(age_at_admit="110", diagnosis_group="Z99", glucose_latest="999999")
    model = build_model().fit(feature_matrix(train), [int(r["readmitted_30d"]) for r in train])
    before = model.named_steps["preprocess"].named_transformers_["numeric"].named_steps["scale"].mean_.copy()
    assert before[0] == 60
    probabilities = model.predict_proba(feature_matrix(future))
    assert np.isfinite(probabilities).all()
    assert np.array_equal(before, model.named_steps["preprocess"].named_transformers_["numeric"].named_steps["scale"].mean_)
    assert not set(FEATURES).intersection({"admission_id", "master_patient_id", "readmitted_30d", "label_status", "glucose_latest"})


def test_aggregate_report_no_identifiers_predictions_or_model_and_no_overwrite(inputs, tmp_path):
    target = tmp_path / "results.json"
    before = [_hash(path) for path in inputs]
    first = run_experiment(*inputs, date(2025, 1, 1), target)
    serialized = target.read_text()
    assert "PRIVATE-" not in serialized
    assert str(tmp_path) not in serialized
    assert first["governance"]["release_status"] == "DEMONSTRATION_ONLY"
    assert first["split"]["shared_master_patients"] == 0
    assert first["evaluation"]["training_prevalence_baseline"]["roc_auc"] == 0.5
    assert before == [_hash(path) for path in inputs]
    with pytest.raises(MLError, match="Output exists"):
        run_experiment(*inputs, date(2025, 1, 1), target)
    second = run_experiment(*inputs, date(2025, 1, 1), target, overwrite=True)
    first.pop("created_at_utc")
    second.pop("created_at_utc")
    assert first == second
    assert {p.name for p in tmp_path.iterdir()} == {"gold.csv", "master.csv", "identity.json", "gold-audit.json", "results.json"}


def test_small_confusion_cells_suppressed_and_errors_sanitized(inputs, tmp_path, capsys):
    result = metrics(np.array([0] * 20 + [1] * 20), np.full(40, 0.2))
    assert result["confusion_matrix_at_0_5"] is None
    assert result["confusion_matrix_suppressed"] is True
    inputs[0].write_text(inputs[0].read_text().replace("Lakeside General", "PRIVATE-BAD-HOSPITAL"))
    target = tmp_path / "results.json"
    assert main(["--gold", str(inputs[0]), "--patient-master", str(inputs[1]),
                 "--identity-audit", str(inputs[2]), "--gold-audit", str(inputs[3]),
                 "--output", str(target)]) == 1
    assert "PRIVATE" not in capsys.readouterr().out
    assert not target.exists()


def test_nonfinite_and_negative_numeric_features_rejected():
    bad = row(1)
    for value in ("nan", "inf", "-1"):
        bad["prior_admission_30d_count"] = value
        with pytest.raises(MLError, match="numeric"):
            feature_matrix([bad])


def test_incomplete_positive_followup_is_excluded(inputs):
    with inputs[0].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[84].update(admit_date="2025-12-16", discharge_date="2025-12-20")
    write_csv(inputs[0], GOLD_FIELDS, rows)
    _, usable, _ = load_cohort(*inputs)
    assert len(usable) == 157
    assert "PRIVATE-PATIENT-84" not in {r["master_patient_id"] for r in usable}


def test_nonconvergence_preserves_previous_output(inputs, tmp_path, monkeypatch, capsys):
    import warnings
    from sklearn.exceptions import ConvergenceWarning
    from patientra.ml import readmission

    class Nonconverging:
        def fit(self, *_):
            warnings.warn("PRIVATE-ESTIMATOR-DETAIL", ConvergenceWarning)

    monkeypatch.setattr(readmission, "build_model", Nonconverging)
    target = tmp_path / "previous.json"
    target.write_text('{"previous": true}')
    assert main(["--gold", str(inputs[0]), "--patient-master", str(inputs[1]),
                 "--identity-audit", str(inputs[2]), "--gold-audit", str(inputs[3]),
                 "--output", str(target), "--overwrite"]) == 1
    assert target.read_text() == '{"previous": true}'
    assert "PRIVATE" not in capsys.readouterr().out
