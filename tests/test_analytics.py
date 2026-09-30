import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from patientra.analytics import (
    AnalyticsConfig,
    AnalyticsError,
    build_analytics,
)
from patientra.features.gold import GOLD_FIELDS


FIXED_TIME = datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc)
FIXED_RUN_ID = "00000000-0000-4000-8000-000000000500"


def _row(
    number: int,
    label: str,
    label_status: str,
    *,
    hospital: str = "Lakeside General",
    sex: str = "F",
    age: int = 60,
    diagnosis: str = "I50",
    discharge_status: str = "home",
    discharge_date: str = "2025-06-05",
    length_of_stay: int | None = 4,
    prior_count: int = 0,
) -> dict[str, str]:
    row = {field: "" for field in GOLD_FIELDS}
    row.update(
        {
            "admission_id": f"SYNTHETIC-ADMISSION-{number}",
            "master_patient_id": f"SYNTHETIC-MASTER-{number}",
            "hospital": hospital,
            "admit_date": "2025-06-01",
            "discharge_date": discharge_date,
            "age_at_admit": str(age),
            "sex": sex,
            "diagnosis_group": diagnosis,
            "discharge_status": discharge_status,
            "length_of_stay_days": "" if length_of_stay is None else str(length_of_stay),
            "prior_completed_admission_count": str(prior_count),
            "prior_admission_30d_count": "0",
            "prior_admission_365d_count": "0",
            "prior_same_diagnosis_group_count": "0",
            "prior_distinct_hospital_count": "0",
            "glucose_count": "0",
            "haemoglobin_count": "0",
            "creatinine_count": "0",
            "readmitted_30d": label,
            "label_status": label_status,
            "observation_end_date": "2025-12-31",
            "feature_rule_version": "phase4-gold-v1",
        }
    )
    return row


def _write(path: Path, rows: list[dict[str, str]], fields=GOLD_FIELDS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _eligible_rows(positive: int, negative: int) -> list[dict[str, str]]:
    return [
        *[
            _row(index, "1", "labeled_positive")
            for index in range(1, positive + 1)
        ],
        *[
            _row(index, "0", "labeled_negative")
            for index in range(positive + 1, positive + negative + 1)
        ],
    ]


def test_analytics_uses_only_eligible_labels_and_omits_identifiers(tmp_path: Path) -> None:
    rows = _eligible_rows(10, 30)
    rows.extend(
        [
            _row(
                41,
                "",
                "excluded_died",
                discharge_status="died",
            ),
            _row(
                42,
                "",
                "excluded_no_discharge",
                discharge_status="still_admitted",
                discharge_date="",
                length_of_stay=None,
            ),
            _row(43, "", "censored_incomplete_30d_followup"),
        ]
    )
    gold = _write(tmp_path / "gold.csv", rows)
    result = build_analytics(
        gold,
        tmp_path / "analytics",
        AnalyticsConfig(minimum_cell_size=1),
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["cohort"]["gold_admissions"] == 43
    assert report["cohort"]["eligible_admissions"] == 40
    assert report["cohort"]["excluded_admissions"] == 3
    assert report["overall"]["readmitted_admissions"] == 10
    assert report["overall"]["not_readmitted_admissions"] == 30
    assert report["overall"]["readmission_rate_pct"] == 25.0
    serialized = "".join(
        Path(path).read_text(encoding="utf-8")
        for path in (result.report_path, result.breakdown_path, result.audit_path)
    )
    assert "SYNTHETIC-ADMISSION-1" not in serialized
    assert "SYNTHETIC-MASTER-1" not in serialized


def test_analytics_applies_primary_and_complementary_suppression(tmp_path: Path) -> None:
    rows: list[dict[str, str]] = []
    number = 1
    for diagnosis, positive, negative in (("I50", 2, 3), ("E11", 15, 15), ("J18", 15, 15)):
        for label, status, count in (
            ("1", "labeled_positive", positive),
            ("0", "labeled_negative", negative),
        ):
            for _ in range(count):
                rows.append(_row(number, label, status, diagnosis=diagnosis))
                number += 1
    result = build_analytics(
        _write(tmp_path / "gold.csv", rows),
        tmp_path / "analytics",
        AnalyticsConfig(minimum_cell_size=11),
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    diagnosis = {
        row["category"]: row for row in report["breakdowns"]["diagnosis_group"]
    }
    assert diagnosis["I50"]["suppression_reason"] == "primary_small_cell"
    assert diagnosis["E11"]["suppression_reason"] == "complementary_suppression"
    assert diagnosis["J18"]["eligible_admissions"] == 30
    assert diagnosis["I50"]["eligible_admissions"] is None
    assert result.suppressed_breakdown_rows >= 2


def test_analytics_fails_closed_on_schema_and_label_conflicts(tmp_path: Path) -> None:
    rows = _eligible_rows(2, 2)
    bad_schema = _write(
        tmp_path / "bad-schema.csv",
        rows,
        fields=(*GOLD_FIELDS, "unexpected"),
    )
    with pytest.raises(AnalyticsError, match="schema"):
        build_analytics(
            bad_schema,
            tmp_path / "bad-schema-output",
            AnalyticsConfig(minimum_cell_size=1),
        )

    rows[0]["readmitted_30d"] = "0"
    conflict = _write(tmp_path / "conflict.csv", rows)
    with pytest.raises(AnalyticsError, match="inconsistent"):
        build_analytics(
            conflict,
            tmp_path / "conflict-output",
            AnalyticsConfig(minimum_cell_size=1),
        )


def test_analytics_is_reproducible_immutable_and_overwrite_protected(tmp_path: Path) -> None:
    gold = _write(tmp_path / "gold.csv", _eligible_rows(4, 4))
    source_before = gold.read_bytes()
    config = AnalyticsConfig(minimum_cell_size=1)
    first = build_analytics(
        gold,
        tmp_path / "first",
        config,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    second = build_analytics(
        gold,
        tmp_path / "second",
        config,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    assert Path(first.report_path).read_bytes() == Path(second.report_path).read_bytes()
    assert Path(first.breakdown_path).read_bytes() == Path(second.breakdown_path).read_bytes()
    assert gold.read_bytes() == source_before
    with pytest.raises(AnalyticsError, match="already exist"):
        build_analytics(gold, tmp_path / "first", config)
    rerun = build_analytics(
        gold,
        tmp_path / "first",
        config,
        overwrite=True,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    assert rerun.eligible_rows == 8
