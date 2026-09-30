import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from patientra.ingestion import ingest_csv
from patientra.transformations import SilverConfig, SilverError, build_silver


FIXED_TIME = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _read_dicts(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bronze_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    raw = tmp_path / "raw"
    patients = _write(
        raw / "patients.csv",
        "patient_id,source_system,first_name,last_name,date_of_birth,sex,phone,state\n"
        "LG-000001,LG,SYNTHETIC,One,1980-01-02,M,000,AA\n"
        "RS00001,RS,SYNTHETIC,Two,31/12/1985,1,111,BB\n"
        "RS00002,RS,SYNTHETIC,Three,02/03/1985,2,222,CC\n",
    )
    admissions = _write(
        raw / "admissions.csv",
        "admission_id,patient_id,hospital,admit_date,discharge_date,diagnosis_code,discharge_status\n"
        "A1,LG-000001,Lakeside General,2025-01-01,2025-01-03,i509,home\n"
        "A2,RS00001,Riverside Specialist,05/01/2025,07/01/2025,j189,home\n"
        "A2,RS00001,Riverside Specialist,05/01/2025,07/01/2025,j189,home\n"
        "A3,RS00002,Riverside Specialist,08/01/2025,,O80,still_admitted\n",
    )
    labs = _write(
        raw / "lab_results.csv",
        "lab_id,admission_id,test_name,result_value,unit,result_time\n"
        "L1,A1,glucose,5.5,mmol/L,2025-01-02 08:00:00\n"
        "L2,A2,haemoglobin,130,g/L,2025-01-06 09:00:00\n"
        "L3,A2,creatinine,88.4,umol/L,2025-01-06 10:00:00\n"
        "L4,A1,glucose,100,mg/dL,2025-01-04 08:00:00\n",
    )

    results = []
    for number, source in enumerate((patients, admissions, labs), start=1):
        results.append(
            ingest_csv(
                source,
                "Lakeside Health Network",
                tmp_path / "bronze",
                tmp_path / "bronze_quarantine",
                run_id=f"00000000-0000-4000-8000-{number:012d}",
                ingested_at=FIXED_TIME,
            )
        )
    return tuple(Path(result.bronze_path) for result in results)


def test_silver_standardizes_converts_deduplicates_and_audits(tmp_path: Path) -> None:
    patients, admissions, labs = _bronze_inputs(tmp_path)
    result = build_silver(
        patients,
        admissions,
        labs,
        tmp_path / "silver",
        tmp_path / "quarantine",
        config=SilverConfig(
            slash_date_order="dmy", numeric_sex_codes=(("1", "M"), ("2", "F"))
        ),
        run_id="00000000-0000-4000-8000-000000000099",
        created_at=FIXED_TIME,
    )

    assert result.source_rows == {"patients": 3, "admissions": 4, "lab_results": 4}
    assert result.silver_rows == {"patients": 3, "admissions": 3, "lab_results": 3}
    assert result.quarantine_rows == {"patients": 0, "admissions": 1, "lab_results": 1}
    assert result.quarantine_reason_counts["admissions"] == {"duplicate_record": 1}
    assert result.quarantine_reason_counts["lab_results"] == {
        "result_after_discharge": 1
    }
    assert result.transformation_counts["lab_results"] == {
        "g/L_div_10": 1,
        "mmol/L_x_18.016": 1,
        "umol/L_div_88.4": 1,
    }

    patient_rows = _read_dicts(result.silver_paths["patients"])
    assert [(row["date_of_birth"], row["sex"]) for row in patient_rows] == [
        ("1980-01-02", "M"),
        ("1985-12-31", "M"),
        ("1985-03-02", "F"),
    ]
    admission_rows = _read_dicts(result.silver_paths["admissions"])
    assert [row["diagnosis_code"] for row in admission_rows] == ["I50.9", "J18.9", "O80"]
    lab_rows = _read_dicts(result.silver_paths["lab_results"])
    assert [
        (row["test_name"], row["result_value"], row["unit"], row["conversion_applied"])
        for row in lab_rows
    ] == [
        ("glucose", "99.088", "mg/dL", "mmol/L_x_18.016"),
        ("haemoglobin", "13", "g/dL", "g/L_div_10"),
        ("creatinine", "1", "mg/dL", "umol/L_div_88.4"),
    ]


def test_unconfigured_ambiguous_codes_are_quarantined_not_guessed(tmp_path: Path) -> None:
    patients, admissions, labs = _bronze_inputs(tmp_path)
    result = build_silver(
        patients,
        admissions,
        labs,
        tmp_path / "silver",
        tmp_path / "quarantine",
        config=SilverConfig(),
    )

    assert result.silver_rows["patients"] == 1
    assert result.quarantine_reason_counts["patients"] == {
        "unconfigured_slash_date_date_of_birth": 2,
        "unmapped_numeric_sex_code": 2,
    }
    assert result.quarantine_reason_counts["admissions"]["unknown_patient_id"] == 3


def test_conflicting_primary_key_quarantines_every_version(tmp_path: Path) -> None:
    patients, admissions, labs = _bronze_inputs(tmp_path)
    with admissions.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    rows[3][4] = "08/01/2025"
    with admissions.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    result = build_silver(
        patients,
        admissions,
        labs,
        tmp_path / "silver",
        tmp_path / "quarantine",
        config=SilverConfig(
            slash_date_order="dmy", numeric_sex_codes=(("1", "M"), ("2", "F"))
        ),
    )

    assert result.quarantine_reason_counts["admissions"] == {
        "duplicate_primary_key_conflict": 2
    }
    assert result.quarantine_reason_counts["lab_results"]["unknown_admission_id"] == 2


def test_schema_drift_fails_closed(tmp_path: Path) -> None:
    patients, admissions, labs = _bronze_inputs(tmp_path)
    text = patients.read_text(encoding="utf-8")
    patients.write_text(text.replace("patient_id,", "unexpected,patient_id,", 1), encoding="utf-8")

    with pytest.raises(SilverError, match="Schema drift"):
        build_silver(
            patients,
            admissions,
            labs,
            tmp_path / "silver",
            tmp_path / "quarantine",
        )
