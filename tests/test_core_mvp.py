import csv
import json
from pathlib import Path

import pytest

from patientra.features.gold import GOLD_FIELDS
from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.mvp import CoreMvpError, build_core_mvp
from patientra.transformations.silver import ADMISSION_COLUMNS


SILVER_FIELDS = (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS)


def _write_csv(
    path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _silver_row(
    number: int,
    patient_id: str,
    admit_date: str,
    discharge_date: str,
) -> dict[str, str]:
    row = {field: "" for field in SILVER_FIELDS}
    row.update(
        {
            "admission_id": f"PRIVATE-ADMISSION-{number}",
            "patient_id": patient_id,
            "hospital": "Lakeside General" if number % 2 else "Riverside Specialist",
            "admit_date": admit_date,
            "discharge_date": discharge_date,
            "diagnosis_code": "I50.9",
            "discharge_status": "home",
            "_source_system": "SYNTHETIC",
            "_source_file": "admissions.csv",
            "_source_row_number": str(number + 1),
            "_source_sha256": "a" * 64,
            "_ingested_at_utc": "2026-01-01T00:00:00Z",
            "_ingestion_run_id": "00000000-0000-4000-8000-000000000001",
        }
    )
    return row


def _gold_row(
    number: int,
    master_id: str,
    admit_date: str,
    discharge_date: str,
    label: str,
    diagnosis: str = "I50",
) -> dict[str, str]:
    row = {field: "" for field in GOLD_FIELDS}
    row.update(
        {
            "admission_id": f"PRIVATE-ADMISSION-{number}",
            "master_patient_id": master_id,
            "hospital": "Lakeside General" if number % 2 else "Riverside Specialist",
            "admit_date": admit_date,
            "discharge_date": discharge_date,
            "age_at_admit": "60",
            "sex": "F",
            "diagnosis_group": diagnosis,
            "discharge_status": "home",
            "length_of_stay_days": "4",
            "prior_completed_admission_count": "0",
            "prior_admission_30d_count": "0",
            "prior_admission_365d_count": "0",
            "prior_same_diagnosis_group_count": "0",
            "prior_distinct_hospital_count": "0",
            "glucose_count": "0",
            "haemoglobin_count": "0",
            "creatinine_count": "0",
            "readmitted_30d": label,
            "label_status": "labeled_positive" if label == "1" else "labeled_negative",
            "observation_end_date": "2025-12-31",
            "feature_rule_version": "phase4-gold-v1",
        }
    )
    return row


def _fixture(tmp_path: Path) -> dict[str, Path]:
    stays = [
        (1, "LOCAL-A", "MASTER-1", "2025-01-01", "2025-01-05", "1"),
        (2, "LOCAL-B", "MASTER-1", "2025-01-20", "2025-01-24", "0"),
        (3, "LOCAL-C", "MASTER-2", "2025-02-01", "2025-02-05", "1"),
        (4, "LOCAL-C", "MASTER-2", "2025-02-20", "2025-02-24", "0"),
        (5, "LOCAL-D", "MASTER-3", "2025-03-01", "2025-03-05", "0"),
    ]
    silver = _write_csv(
        tmp_path / "admissions.silver.csv",
        SILVER_FIELDS,
        [_silver_row(number, patient, admit, discharge) for number, patient, _, admit, discharge, _ in stays],
    )
    gold_rows = [
        _gold_row(number, master, admit, discharge, label)
        for number, _, master, admit, discharge, label in stays
    ]
    gold_rows[-1]["diagnosis_group"] = "J18"
    gold = _write_csv(
        tmp_path / "readmission_features.csv",
        GOLD_FIELDS,
        gold_rows,
    )
    identity = _write_json(
        tmp_path / "identity_audit.json",
        {
            "rule_version": "phase3-identity-v1",
            "auto_matches": 12,
            "review_candidates": 3,
            "human_accepted_matches": 1,
            "review_status_counts": {"ACCEPTED": 1, "REJECTED": 1, "ABSTAINED": 0},
        },
    )
    analytics = _write_json(
        tmp_path / "readmission_analytics.json",
        {
            "analytics_rule_version": "phase5-analytics-v1",
            "gold_feature_rule_version": "phase4-gold-v1",
            "overall": {
                "eligible_admissions": 5,
                "readmitted_admissions": 2,
                "readmission_rate_pct": 40.0,
            },
            "breakdowns": {
                "diagnosis_group": [
                    {
                        "category": "I50",
                        "eligible_admissions": 4,
                        "readmitted_admissions": 2,
                        "readmission_rate_pct": 50.0,
                        "suppression_reason": "",
                    },
                    {
                        "category": "O80",
                        "eligible_admissions": None,
                        "readmitted_admissions": None,
                        "readmission_rate_pct": None,
                        "suppression_reason": "primary_small_cell",
                    },
                    {
                        "category": "J18",
                        "eligible_admissions": 1,
                        "readmitted_admissions": 0,
                        "readmission_rate_pct": 0.0,
                        "suppression_reason": "",
                    },
                ]
            },
        },
    )
    return {"silver": silver, "gold": gold, "identity": identity, "analytics": analytics}


def test_core_mvp_calculates_all_three_answers_without_identifiers(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    output = tmp_path / "patientra_core_mvp.json"
    result = build_core_mvp(
        inputs["silver"], inputs["gold"], inputs["identity"], inputs["analytics"], output
    )

    assert result.before_matching_rate_pct == 20.0
    assert result.after_matching_rate_pct == 40.0
    assert result.hidden_readmissions == 1
    assert result.highest_diagnosis_group == "I50"
    assert result.highest_diagnosis_rate_pct == 50.0
    assert result.automatic_matches == 12
    assert result.review_candidates == 3
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["questions"]["identity_resolution_workload"]["human_review_outcomes"]["pending"] == 1
    serialized = output.read_text(encoding="utf-8")
    assert "PRIVATE-ADMISSION" not in serialized
    assert "LOCAL-A" not in serialized
    assert "MASTER-1" not in serialized


def test_core_mvp_is_reproducible_and_overwrite_protected(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    arguments = (inputs["silver"], inputs["gold"], inputs["identity"], inputs["analytics"])
    build_core_mvp(*arguments, first)
    build_core_mvp(*arguments, second)
    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(CoreMvpError, match="already exists"):
        build_core_mvp(*arguments, first)
    build_core_mvp(*arguments, first, overwrite=True)


def test_core_mvp_fails_closed_on_schema_or_analytics_drift(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    malformed = tmp_path / "bad-schema.csv"
    malformed.write_text("admission_id,unexpected\nA,B\n", encoding="utf-8")
    with pytest.raises(CoreMvpError, match="schema"):
        build_core_mvp(
            malformed,
            inputs["gold"],
            inputs["identity"],
            inputs["analytics"],
            tmp_path / "bad-schema.json",
        )

    report = json.loads(inputs["analytics"].read_text(encoding="utf-8"))
    report["overall"]["readmitted_admissions"] = 3
    _write_json(inputs["analytics"], report)
    with pytest.raises(CoreMvpError, match="reconcile"):
        build_core_mvp(
            inputs["silver"],
            inputs["gold"],
            inputs["identity"],
            inputs["analytics"],
            tmp_path / "bad-analytics.json",
        )
