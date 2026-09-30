import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from patientra.features import GoldConfig, GoldError, build_gold
from patientra.features.gold import GOLD_FIELDS, SILVER_LAB_FIELDS
from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.matching.identity import MASTER_FIELDS
from patientra.transformations.silver import ADMISSION_COLUMNS, PATIENT_COLUMNS


FIXED_TIME = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
FIXED_RUN_ID = "00000000-0000-4000-8000-000000000400"


def _lineage(row_number: int) -> dict[str, str]:
    return {
        "_source_system": "SYNTHETIC TEST",
        "_source_file": "synthetic.csv",
        "_source_row_number": str(row_number),
        "_source_sha256": "a" * 64,
        "_ingested_at_utc": "2026-01-01T00:00:00Z",
        "_ingestion_run_id": "00000000-0000-4000-8000-000000000001",
    }


def _write(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _patient(
    patient_id: str, source: str, birth: str, sex: str, row_number: int
) -> dict[str, str]:
    return {
        "patient_id": patient_id,
        "source_system": source,
        "first_name": f"SYNTHETIC-{patient_id}-FIRST",
        "last_name": f"SYNTHETIC-{patient_id}-LAST",
        "date_of_birth": birth,
        "sex": sex,
        "phone": f"SYNTHETIC-PHONE-{patient_id}",
        "state": "ZZ",
        **_lineage(row_number),
    }


def _admission(
    admission_id: str,
    patient_id: str,
    hospital: str,
    admit: str,
    discharge: str,
    status: str,
    diagnosis: str,
    row_number: int,
) -> dict[str, str]:
    return {
        "admission_id": admission_id,
        "patient_id": patient_id,
        "hospital": hospital,
        "admit_date": admit,
        "discharge_date": discharge,
        "diagnosis_code": diagnosis,
        "discharge_status": status,
        **_lineage(row_number),
    }


def _lab(
    lab_id: str,
    admission_id: str,
    test: str,
    value: str,
    unit: str,
    result_time: str,
    row_number: int,
) -> dict[str, str]:
    return {
        "lab_id": lab_id,
        "admission_id": admission_id,
        "test_name": test,
        "result_value": value,
        "unit": unit,
        "result_time": result_time,
        "result_value_original": value,
        "unit_original": unit,
        "conversion_applied": "none",
        **_lineage(row_number),
    }


def _master(
    master_id: str, patient_id: str, source: str, status: str = "LINKED"
) -> dict[str, str]:
    return {
        "master_patient_id": master_id,
        "patient_id": patient_id,
        "source_system": source,
        "link_status": status,
        "match_case_id": "SYNTHETIC-CASE",
        "rule_version": "phase3-identity-v1",
    }


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    patients = _write(
        tmp_path / "patients.silver.csv",
        (*PATIENT_COLUMNS, *LINEAGE_COLUMNS),
        [
            _patient("LG-TEST-1", "LG", "1980-01-02", "F", 2),
            _patient("RS-TEST-1", "RS", "1980-01-02", "F", 3),
            _patient("LG-TEST-2", "LG", "1970-06-15", "M", 4),
        ],
    )
    admissions = _write(
        tmp_path / "admissions.silver.csv",
        (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS),
        [
            _admission(
                "ADM-1", "LG-TEST-1", "Lakeside General", "2025-01-01",
                "2025-01-05", "home", "I50.9", 2,
            ),
            _admission(
                "ADM-2", "RS-TEST-1", "Riverside Specialist", "2025-01-05",
                "2025-01-08", "home", "I50.1", 3,
            ),
            _admission(
                "ADM-3", "RS-TEST-1", "Riverside Specialist", "2025-03-01",
                "2025-03-03", "home", "J18.9", 4,
            ),
        ],
    )
    labs = _write(
        tmp_path / "lab_results.silver.csv",
        SILVER_LAB_FIELDS,
        [
            _lab("LAB-1", "ADM-1", "glucose", "90", "mg/dL", "2025-01-01T10:00:00", 2),
            _lab("LAB-2", "ADM-1", "glucose", "110", "mg/dL", "2025-01-04T10:00:00", 3),
            _lab("LAB-3", "ADM-2", "creatinine", "1.2", "mg/dL", "2025-01-06T10:00:00", 4),
        ],
    )
    master = _write(
        tmp_path / "patient_master.csv",
        MASTER_FIELDS,
        [
            _master("MP-SYNTHETIC-1", "LG-TEST-1", "LG"),
            _master("MP-SYNTHETIC-1", "RS-TEST-1", "RS"),
            _master("MP-SYNTHETIC-2", "LG-TEST-2", "LG", "UNLINKED"),
        ],
    )
    return patients, admissions, labs, master


def _read(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_gold_builds_inclusive_label_history_labs_and_privacy(tmp_path: Path) -> None:
    patients, admissions, labs, master = _inputs(tmp_path)
    result = build_gold(
        patients,
        admissions,
        labs,
        master,
        tmp_path / "gold",
        GoldConfig(observation_end=date(2025, 12, 31)),
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )

    rows = _read(result.output_path)
    by_id = {row["admission_id"]: row for row in rows}
    assert tuple(rows[0]) == GOLD_FIELDS
    assert result.patient_master_unique_patients == 2
    assert result.gold_unique_master_patients == 1
    assert result.label_counts == {"negative": 2, "positive": 1}
    assert by_id["ADM-1"]["readmitted_30d"] == "1"
    assert by_id["ADM-1"]["label_status"] == "labeled_positive"
    assert by_id["ADM-2"]["prior_completed_admission_count"] == "1"
    assert by_id["ADM-2"]["prior_admission_30d_count"] == "1"
    assert by_id["ADM-2"]["prior_same_diagnosis_group_count"] == "1"
    assert by_id["ADM-2"]["days_since_prior_discharge"] == "0"
    assert by_id["ADM-1"]["glucose_count"] == "2"
    assert by_id["ADM-1"]["glucose_first"] == "90"
    assert by_id["ADM-1"]["glucose_latest"] == "110"
    assert by_id["ADM-1"]["glucose_mean"] == "100"
    assert "patient_id" not in rows[0]
    assert "first_name" not in rows[0]
    assert "phone" not in rows[0]
    serialized = Path(result.output_path).read_text(encoding="utf-8")
    audit = Path(result.audit_path).read_text(encoding="utf-8")
    assert "SYNTHETIC-PHONE" not in serialized + audit
    assert "SYNTHETIC-LG-TEST-1-FIRST" not in serialized + audit
    assert "LG-TEST-1" not in serialized + audit


def test_gold_includes_day_30_boundary(tmp_path: Path) -> None:
    patients, _, _, master = _inputs(tmp_path)
    admissions = _write(
        tmp_path / "boundary-admissions.csv",
        (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS),
        [
            _admission(
                "ADM-BOUNDARY-1", "LG-TEST-1", "Lakeside General", "2025-01-01",
                "2025-01-05", "home", "I50.9", 2,
            ),
            _admission(
                "ADM-BOUNDARY-2", "RS-TEST-1", "Riverside Specialist", "2025-02-04",
                "2025-02-06", "home", "I50.1", 3,
            ),
        ],
    )
    empty_labs = _write(tmp_path / "boundary-labs.csv", SILVER_LAB_FIELDS, [])
    result = build_gold(
        patients,
        admissions,
        empty_labs,
        master,
        tmp_path / "gold-boundary",
        GoldConfig(observation_end=date(2025, 12, 31)),
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    by_id = {row["admission_id"]: row for row in _read(result.output_path)}
    assert by_id["ADM-BOUNDARY-1"]["readmitted_30d"] == "1"
    assert by_id["ADM-BOUNDARY-1"]["label_status"] == "labeled_positive"


def test_gold_excludes_death_no_discharge_and_right_censoring(tmp_path: Path) -> None:
    patients, _, labs, master = _inputs(tmp_path)
    admissions = _write(
        tmp_path / "status-admissions.csv",
        (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS),
        [
            _admission(
                "ADM-DIED", "LG-TEST-1", "Lakeside General", "2025-10-01",
                "2025-10-05", "died", "I50.9", 2,
            ),
            _admission(
                "ADM-STILL", "RS-TEST-1", "Riverside Specialist", "2025-12-15",
                "", "still_admitted", "J18.9", 3,
            ),
            _admission(
                "ADM-CENSORED", "LG-TEST-2", "Lakeside General", "2025-12-18",
                "2025-12-20", "home", "E11.9", 4,
            ),
        ],
    )
    empty_labs = _write(tmp_path / "empty-labs.csv", SILVER_LAB_FIELDS, [])
    result = build_gold(
        patients,
        admissions,
        empty_labs,
        master,
        tmp_path / "gold-status",
        GoldConfig(observation_end=date(2025, 12, 31)),
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    by_id = {row["admission_id"]: row for row in _read(result.output_path)}
    assert by_id["ADM-DIED"]["label_status"] == "excluded_died"
    assert by_id["ADM-STILL"]["label_status"] == "excluded_no_discharge"
    assert by_id["ADM-CENSORED"]["label_status"] == "censored_incomplete_30d_followup"
    assert all(row["readmitted_30d"] == "" for row in by_id.values())
    assert result.label_counts == {"unlabeled": 3}


def test_gold_observation_end_blocks_future_evidence(tmp_path: Path) -> None:
    patients, admissions, labs, master = _inputs(tmp_path)
    rows = _read(admissions)
    rows.append(
        _admission(
            "ADM-FUTURE", "LG-TEST-2", "Lakeside General", "2026-01-01",
            "2026-01-02", "home", "E11.9", 5,
        )
    )
    _write(admissions, (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS), rows)
    with pytest.raises(GoldError, match="after the observation_end"):
        build_gold(
            patients,
            admissions,
            labs,
            master,
            tmp_path / "future-failure",
            GoldConfig(observation_end=date(2025, 12, 31)),
        )


def test_gold_fails_closed_on_schema_drift_and_master_gaps(tmp_path: Path) -> None:
    patients, admissions, labs, master = _inputs(tmp_path)
    text = patients.read_text(encoding="utf-8")
    patients.write_text(text.replace("patient_id,", "unexpected,patient_id,", 1), encoding="utf-8")
    with pytest.raises(GoldError, match="schema"):
        build_gold(
            patients,
            admissions,
            labs,
            master,
            tmp_path / "schema-failure",
            GoldConfig(observation_end=date(2025, 12, 31)),
        )

    patients, admissions, labs, master = _inputs(tmp_path / "master-gap")
    rows = _read(master)[:-1]
    _write(master, MASTER_FIELDS, rows)
    with pytest.raises(GoldError, match="coverage"):
        build_gold(
            patients,
            admissions,
            labs,
            master,
            tmp_path / "master-failure",
            GoldConfig(observation_end=date(2025, 12, 31)),
        )


def test_gold_requires_explicit_overwrite(tmp_path: Path) -> None:
    patients, admissions, labs, master = _inputs(tmp_path)
    output = tmp_path / "gold"
    config = GoldConfig(observation_end=date(2025, 12, 31))
    build_gold(
        patients,
        admissions,
        labs,
        master,
        output,
        config,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    with pytest.raises(GoldError, match="already exist"):
        build_gold(patients, admissions, labs, master, output, config)
    rerun = build_gold(
        patients,
        admissions,
        labs,
        master,
        output,
        config,
        overwrite=True,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    assert rerun.gold_rows == 3


def test_gold_is_reproducible_with_fixed_run_metadata(tmp_path: Path) -> None:
    patients, admissions, labs, master = _inputs(tmp_path)
    inputs_before = {
        path: path.read_bytes() for path in (patients, admissions, labs, master)
    }
    config = GoldConfig(observation_end=date(2025, 12, 31))
    first = build_gold(
        patients,
        admissions,
        labs,
        master,
        tmp_path / "gold-first",
        config,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    second = build_gold(
        patients,
        admissions,
        labs,
        master,
        tmp_path / "gold-second",
        config,
        run_id=FIXED_RUN_ID,
        created_at=FIXED_TIME,
    )
    assert Path(first.output_path).read_bytes() == Path(second.output_path).read_bytes()
    first_audit = json.loads(Path(first.audit_path).read_text(encoding="utf-8"))
    second_audit = json.loads(Path(second.audit_path).read_text(encoding="utf-8"))
    first_audit.pop("output_path")
    first_audit.pop("audit_path")
    second_audit.pop("output_path")
    second_audit.pop("audit_path")
    assert first_audit == second_audit
    assert {path: path.read_bytes() for path in inputs_before} == inputs_before
