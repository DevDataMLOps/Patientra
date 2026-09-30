import csv
import hashlib
import json
from pathlib import Path

import pytest

from patientra.analytics.readmission import BREAKDOWN_FIELDS
from patientra.features.gold import GOLD_FIELDS
from patientra.validation import ValidationError, validate_release


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _gold_row(number: int, label: str, status: str) -> dict[str, str]:
    row = {field: "" for field in GOLD_FIELDS}
    discharge_status = {
        "excluded_died": "died",
        "excluded_no_discharge": "still_admitted",
    }.get(status, "home")
    has_discharge = status != "excluded_no_discharge"
    row.update(
        {
            "admission_id": f"PRIVATE-ADM-{number}",
            "master_patient_id": f"PRIVATE-MASTER-{number}",
            "hospital": "Lakeside General",
            "admit_date": "2025-01-01",
            "discharge_date": "2025-01-05" if has_discharge else "",
            "age_at_admit": "60",
            "sex": "F",
            "diagnosis_group": "I50",
            "discharge_status": discharge_status,
            "length_of_stay_days": "4" if has_discharge else "",
            "prior_completed_admission_count": "0",
            "prior_admission_30d_count": "0",
            "prior_admission_365d_count": "0",
            "prior_same_diagnosis_group_count": "0",
            "prior_distinct_hospital_count": "0",
            "glucose_count": "0",
            "haemoglobin_count": "0",
            "creatinine_count": "0",
            "readmitted_30d": label,
            "label_status": status,
            "observation_end_date": "2025-12-31",
            "feature_rule_version": "phase4-gold-v1",
        }
    )
    return row


def _release_fixture(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "repo"
    evidence_index = root / "docs/evidence/README.md"
    lines = []
    evidence_names = (
        "phase-1-bronze",
        "phase-2-silver",
        "phase-3-identity-resolution",
        "phase-4-gold-features",
        "phase-5-readmission-analytics",
    )
    for number, name in enumerate(evidence_names, start=1):
        evidence = root / f"docs/evidence/{name}/README.md"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(f"# Phase {number}\n\nComplete\n", encoding="utf-8")
        lines.append(f"| {number} | `{name}/README.md` | Complete |")
    evidence_index.parent.mkdir(parents=True, exist_ok=True)
    evidence_index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / ".gitignore").write_text("data/gold/**\noutputs/**\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "patientra"\nversion = "0.6.1"\n', encoding="utf-8"
    )

    gold_rows = [
        _gold_row(1, "1", "labeled_positive"),
        _gold_row(2, "0", "labeled_negative"),
        _gold_row(3, "", "excluded_died"),
        _gold_row(4, "", "excluded_no_discharge"),
    ]
    gold = _write_csv(root / "data/gold/readmission_features.csv", GOLD_FIELDS, gold_rows)
    gold_audit = _write_json(
        root / "data/gold/readmission_feature_audit.json",
        {
            "rule_version": "phase4-gold-v1",
            "gold_rows": 4,
            "label_counts": {"negative": 1, "positive": 1, "unlabeled": 2},
            "label_status_counts": {
                "excluded_died": 1,
                "excluded_no_discharge": 1,
                "labeled_negative": 1,
                "labeled_positive": 1,
            },
        },
    )
    breakdown_row = {
        "dimension": "hospital",
        "category": "Lakeside General",
        "eligible_admissions": 2,
        "readmitted_admissions": 1,
        "not_readmitted_admissions": 1,
        "readmission_rate_pct": 50.0,
        "wilson_95_lower_pct": 9.45,
        "wilson_95_upper_pct": 90.55,
        "suppression_reason": "",
    }
    analytics_report = _write_json(
        root / "outputs/phase5/readmission_analytics.json",
        {
            "analytics_rule_version": "phase5-analytics-v1",
            "gold_feature_rule_version": "phase4-gold-v1",
            "cohort": {
                "gold_admissions": 4,
                "eligible_admissions": 2,
                "excluded_admissions": 2,
            },
            "overall": {
                "eligible_admissions": 2,
                "readmitted_admissions": 1,
                "not_readmitted_admissions": 1,
                "readmission_rate_pct": 50.0,
            },
            "breakdowns": {"hospital": [breakdown_row]},
        },
    )
    analytics_breakdowns = _write_csv(
        root / "outputs/phase5/readmission_breakdowns.csv",
        BREAKDOWN_FIELDS,
        [breakdown_row],
    )
    analytics_audit = _write_json(
        root / "outputs/phase5/readmission_analytics_audit.json",
        {
            "rule_version": "phase5-analytics-v1",
            "gold_input_sha256": hashlib.sha256(gold.read_bytes()).hexdigest(),
            "suppressed_breakdown_rows": 0,
            "output_sha256": {
                "readmission_analytics.json": hashlib.sha256(
                    analytics_report.read_bytes()
                ).hexdigest(),
                "readmission_breakdowns.csv": hashlib.sha256(
                    analytics_breakdowns.read_bytes()
                ).hexdigest(),
            },
        },
    )
    return {
        "root": root,
        "gold": gold,
        "gold_audit": gold_audit,
        "analytics_report": analytics_report,
        "analytics_breakdowns": analytics_breakdowns,
        "analytics_audit": analytics_audit,
    }


def _validate(paths: dict[str, Path], output: Path, overwrite: bool = False):
    return validate_release(
        paths["root"],
        paths["gold"],
        paths["gold_audit"],
        paths["analytics_report"],
        paths["analytics_breakdowns"],
        paths["analytics_audit"],
        output,
        overwrite=overwrite,
    )


def test_release_validation_reconciles_and_excludes_identifiers(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path)
    first = _validate(paths, tmp_path / "first.json")
    second = _validate(paths, tmp_path / "second.json")
    assert first.status == "PASS"
    assert first.checks_passed == 13
    assert Path(first.output_path).read_bytes() == Path(second.output_path).read_bytes()
    report = Path(first.output_path).read_text(encoding="utf-8")
    assert "PRIVATE-ADM" not in report
    assert "PRIVATE-MASTER" not in report


def test_release_validation_rejects_tampering_and_protects_output(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path)
    output = tmp_path / "validation.json"
    _validate(paths, output)
    with pytest.raises(ValidationError, match="already exists"):
        _validate(paths, output)
    _validate(paths, output, overwrite=True)
    with paths["analytics_breakdowns"].open("a", encoding="utf-8") as handle:
        handle.write("tampered\n")
    with pytest.raises(ValidationError, match="hashes"):
        _validate(paths, tmp_path / "tampered.json")
