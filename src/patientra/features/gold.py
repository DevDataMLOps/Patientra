"""Leakage-controlled Phase 4 Gold features and 30-day readmission labels.

The output has one row per Silver admission and contains no names, phone numbers,
local patient IDs, or laboratory identifiers. Label-ineligible rows remain present
with a blank label and an explicit status so exclusions and right-censoring are
auditable rather than silently converted to negative outcomes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence

from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.matching.identity import MASTER_FIELDS
from patientra.transformations.silver import (
    ADMISSION_COLUMNS,
    LAB_COLUMNS,
    PATIENT_COLUMNS,
)


RULE_VERSION = "phase4-gold-v1"
LAB_TESTS = ("glucose", "haemoglobin", "creatinine")
LAB_SUMMARIES = ("count", "first", "latest", "min", "max", "mean")
SILVER_LAB_FIELDS = (
    *LAB_COLUMNS,
    "result_value_original",
    "unit_original",
    "conversion_applied",
    *LINEAGE_COLUMNS,
)
BASE_GOLD_FIELDS = (
    "admission_id",
    "master_patient_id",
    "hospital",
    "admit_date",
    "discharge_date",
    "age_at_admit",
    "sex",
    "diagnosis_group",
    "discharge_status",
    "length_of_stay_days",
    "prior_completed_admission_count",
    "prior_admission_30d_count",
    "prior_admission_365d_count",
    "prior_same_diagnosis_group_count",
    "prior_distinct_hospital_count",
    "days_since_prior_discharge",
)
LAB_FEATURE_FIELDS = tuple(
    f"{test}_{summary}" for test in LAB_TESTS for summary in LAB_SUMMARIES
)
GOLD_FIELDS = (
    *BASE_GOLD_FIELDS,
    *LAB_FEATURE_FIELDS,
    "readmitted_30d",
    "label_status",
    "observation_end_date",
    "feature_rule_version",
)


class GoldError(RuntimeError):
    """Raised when Gold feature generation cannot complete safely."""


@dataclass(frozen=True)
class GoldConfig:
    """Versioned, explicit configuration for the Gold cohort and label."""

    observation_end: date
    rule_version: str = RULE_VERSION


@dataclass(frozen=True)
class GoldResult:
    """Aggregate-only result containing no patient or admission identifiers."""

    rule_version: str
    run_id: str
    created_at_utc: str
    observation_end_date: str
    input_rows: dict[str, int]
    gold_rows: int
    patient_master_unique_patients: int
    gold_unique_master_patients: int
    label_counts: dict[str, int]
    label_status_counts: dict[str, int]
    lab_presence_counts: dict[str, int]
    output_path: str
    audit_path: str


@dataclass(frozen=True)
class Patient:
    patient_id: str
    source_system: str
    date_of_birth: date
    sex: str


@dataclass(frozen=True)
class Admission:
    admission_id: str
    patient_id: str
    master_patient_id: str
    hospital: str
    admit_date: date
    discharge_date: date | None
    diagnosis_group: str
    discharge_status: str


@dataclass(frozen=True)
class Lab:
    lab_id: str
    admission_id: str
    test_name: str
    result_value: Decimal
    result_time: datetime


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_date(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise GoldError(f"{field} must contain ISO YYYY-MM-DD dates.") from exc
    if parsed.isoformat() != value:
        raise GoldError(f"{field} must contain canonical ISO YYYY-MM-DD dates.")
    return parsed


def _parse_optional_date(value: str, field: str) -> date | None:
    return _parse_date(value, field) if value else None


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoldError(f"{field} must contain ISO datetimes.") from exc
    return parsed


def _read_csv(
    path: str | Path,
    expected_fields: Sequence[str],
    label: str,
) -> tuple[Path, list[dict[str, str]]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise GoldError(f"The {label} input must be an existing regular file.")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(expected_fields):
                raise GoldError(f"The {label} schema does not match the Phase 4 contract.")
            rows = list(reader)
    except GoldError:
        raise
    except (csv.Error, UnicodeError, OSError) as exc:
        raise GoldError(f"The {label} input could not be read safely.") from exc
    return source, rows


def _unique_rows(
    rows: Iterable[dict[str, str]], key: str, label: str
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key]
        if not value or value in result:
            raise GoldError(f"The {label} input contains a blank or duplicate {key}.")
        result[value] = row
    return result


def _load_patients(path: str | Path) -> tuple[Path, dict[str, Patient]]:
    source, rows = _read_csv(
        path, (*PATIENT_COLUMNS, *LINEAGE_COLUMNS), "Silver patients"
    )
    unique = _unique_rows(rows, "patient_id", "Silver patients")
    patients: dict[str, Patient] = {}
    for patient_id, row in unique.items():
        if row["sex"] not in {"M", "F"}:
            raise GoldError("Silver patients contain a noncanonical sex value.")
        patients[patient_id] = Patient(
            patient_id=patient_id,
            source_system=row["source_system"],
            date_of_birth=_parse_date(row["date_of_birth"], "date_of_birth"),
            sex=row["sex"],
        )
    return source, patients


def _load_master(
    path: str | Path, patients: dict[str, Patient]
) -> tuple[Path, dict[str, str]]:
    source, rows = _read_csv(path, MASTER_FIELDS, "patient master")
    unique = _unique_rows(rows, "patient_id", "patient master")
    if set(unique) != set(patients):
        raise GoldError("Patient master coverage does not match Silver patients.")
    mapping: dict[str, str] = {}
    for patient_id, row in unique.items():
        if not row["master_patient_id"]:
            raise GoldError("Patient master contains a blank master_patient_id.")
        if row["source_system"] != patients[patient_id].source_system:
            raise GoldError("Patient master source_system conflicts with Silver patients.")
        mapping[patient_id] = row["master_patient_id"]
    return source, mapping


def _diagnosis_group(code: str) -> str:
    compact = code.replace(".", "")
    if len(compact) < 3:
        raise GoldError("Silver admissions contain an invalid diagnosis_code.")
    return compact[:3]


def _load_admissions(
    path: str | Path,
    patients: dict[str, Patient],
    master_by_patient: dict[str, str],
) -> tuple[Path, list[Admission]]:
    source, rows = _read_csv(
        path, (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS), "Silver admissions"
    )
    unique = _unique_rows(rows, "admission_id", "Silver admissions")
    admissions: list[Admission] = []
    for admission_id, row in unique.items():
        patient_id = row["patient_id"]
        if patient_id not in patients or patient_id not in master_by_patient:
            raise GoldError("Silver admissions contain an unmapped patient_id.")
        admit_date = _parse_date(row["admit_date"], "admit_date")
        discharge_date = _parse_optional_date(row["discharge_date"], "discharge_date")
        if discharge_date is not None and discharge_date < admit_date:
            raise GoldError("Silver admissions contain invalid stay chronology.")
        if row["discharge_status"] == "still_admitted" and discharge_date is not None:
            raise GoldError("A still-admitted stay cannot have a discharge date.")
        if row["discharge_status"] != "still_admitted" and discharge_date is None:
            raise GoldError("A completed stay must have a discharge date.")
        admissions.append(
            Admission(
                admission_id=admission_id,
                patient_id=patient_id,
                master_patient_id=master_by_patient[patient_id],
                hospital=row["hospital"],
                admit_date=admit_date,
                discharge_date=discharge_date,
                diagnosis_group=_diagnosis_group(row["diagnosis_code"]),
                discharge_status=row["discharge_status"],
            )
        )
    admissions.sort(key=lambda item: (item.admit_date, item.admission_id))
    return source, admissions


def _load_labs(
    path: str | Path, admissions: Sequence[Admission]
) -> tuple[Path, dict[str, list[Lab]]]:
    source, rows = _read_csv(path, SILVER_LAB_FIELDS, "Silver lab results")
    unique = _unique_rows(rows, "lab_id", "Silver lab results")
    admission_ids = {item.admission_id for item in admissions}
    labs_by_admission: dict[str, list[Lab]] = defaultdict(list)
    for lab_id, row in unique.items():
        if row["admission_id"] not in admission_ids:
            raise GoldError("Silver lab results contain an unmapped admission_id.")
        if row["test_name"] not in LAB_TESTS:
            raise GoldError("Silver lab results contain an unsupported test_name.")
        try:
            value = Decimal(row["result_value"])
        except InvalidOperation as exc:
            raise GoldError("Silver lab results contain a nonnumeric result_value.") from exc
        if not value.is_finite():
            raise GoldError("Silver lab results contain a nonfinite result_value.")
        labs_by_admission[row["admission_id"]].append(
            Lab(
                lab_id=lab_id,
                admission_id=row["admission_id"],
                test_name=row["test_name"],
                result_value=value,
                result_time=_parse_datetime(row["result_time"], "result_time"),
            )
        )
    for labs in labs_by_admission.values():
        labs.sort(key=lambda item: (item.result_time, item.lab_id))
    return source, labs_by_admission


def _age_at(birth: date, as_of: date) -> int:
    age = as_of.year - birth.year - (
        (as_of.month, as_of.day) < (birth.month, birth.day)
    )
    if age < 0 or age > 120:
        raise GoldError("A calculated age falls outside the supported range 0-120.")
    return age


def _format_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def _lab_features(labs: Sequence[Lab]) -> dict[str, str]:
    result = {field: "" for field in LAB_FEATURE_FIELDS}
    by_test: dict[str, list[Lab]] = defaultdict(list)
    for lab in labs:
        by_test[lab.test_name].append(lab)
    for test in LAB_TESTS:
        observations = by_test.get(test, [])
        result[f"{test}_count"] = str(len(observations))
        if not observations:
            continue
        values = [item.result_value for item in observations]
        result[f"{test}_first"] = _format_decimal(values[0])
        result[f"{test}_latest"] = _format_decimal(values[-1])
        result[f"{test}_min"] = _format_decimal(min(values))
        result[f"{test}_max"] = _format_decimal(max(values))
        result[f"{test}_mean"] = _format_decimal(
            sum(values, Decimal("0")) / Decimal(len(values))
        )
    return result


def _label(
    admission: Admission,
    patient_admissions: Sequence[Admission],
    observation_end: date,
) -> tuple[str, str]:
    if admission.discharge_status == "died":
        return "", "excluded_died"
    if admission.discharge_date is None:
        return "", "excluded_no_discharge"
    possible = [
        other
        for other in patient_admissions
        if other.admission_id != admission.admission_id
        and other.admit_date >= admission.discharge_date
        and other.admit_date <= observation_end
    ]
    if possible:
        next_admission = min(possible, key=lambda item: (item.admit_date, item.admission_id))
        gap = (next_admission.admit_date - admission.discharge_date).days
        if 0 <= gap <= 30:
            return "1", "labeled_positive"
    if admission.discharge_date + timedelta(days=30) <= observation_end:
        return "0", "labeled_negative"
    return "", "censored_incomplete_30d_followup"


def _history_features(
    admission: Admission, patient_admissions: Sequence[Admission]
) -> dict[str, str]:
    prior = [
        item
        for item in patient_admissions
        if item.admission_id != admission.admission_id
        and item.discharge_date is not None
        and item.discharge_date <= admission.admit_date
    ]
    gaps = [
        (admission.admit_date - item.discharge_date).days
        for item in prior
        if item.discharge_date is not None
    ]
    return {
        "prior_completed_admission_count": str(len(prior)),
        "prior_admission_30d_count": str(sum(0 <= gap <= 30 for gap in gaps)),
        "prior_admission_365d_count": str(sum(0 <= gap <= 365 for gap in gaps)),
        "prior_same_diagnosis_group_count": str(
            sum(item.diagnosis_group == admission.diagnosis_group for item in prior)
        ),
        "prior_distinct_hospital_count": str(len({item.hospital for item in prior})),
        "days_since_prior_discharge": str(min(gaps)) if gaps else "",
    }


def _write_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False, dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=GOLD_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise GoldError("Gold output could not be written atomically.") from exc


def _write_json(path: Path, payload: object) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False, dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise GoldError("Gold audit could not be written atomically.") from exc


def build_gold(
    patients: str | Path,
    admissions: str | Path,
    lab_results: str | Path,
    patient_master: str | Path,
    output_dir: str | Path,
    config: GoldConfig,
    *,
    overwrite: bool = False,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> GoldResult:
    """Build the protected Gold feature table and aggregate-only audit."""

    patient_path, patient_by_id = _load_patients(patients)
    master_path, master_by_patient = _load_master(patient_master, patient_by_id)
    admission_path, admission_rows = _load_admissions(
        admissions, patient_by_id, master_by_patient
    )
    if any(item.admit_date > config.observation_end for item in admission_rows):
        raise GoldError(
            "Silver admissions contain an admit_date after the observation_end."
        )
    lab_path, labs_by_admission = _load_labs(lab_results, admission_rows)

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "readmission_features.csv"
    audit_path = output_root / "readmission_feature_audit.json"
    if not overwrite and (output_path.exists() or audit_path.exists()):
        raise GoldError("Gold outputs already exist; use --overwrite for an intentional rerun.")

    admissions_by_master: dict[str, list[Admission]] = defaultdict(list)
    for admission in admission_rows:
        admissions_by_master[admission.master_patient_id].append(admission)
    for rows in admissions_by_master.values():
        rows.sort(key=lambda item: (item.admit_date, item.admission_id))

    gold_rows: list[dict[str, str]] = []
    label_status_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    lab_presence_counts: Counter[str] = Counter()
    for admission in admission_rows:
        patient = patient_by_id[admission.patient_id]
        history = _history_features(
            admission, admissions_by_master[admission.master_patient_id]
        )
        lab_features = _lab_features(labs_by_admission.get(admission.admission_id, []))
        for test in LAB_TESTS:
            if lab_features[f"{test}_count"] != "0":
                lab_presence_counts[test] += 1
        label, label_status = _label(
            admission,
            admissions_by_master[admission.master_patient_id],
            config.observation_end,
        )
        label_status_counts[label_status] += 1
        label_counts[{"1": "positive", "0": "negative", "": "unlabeled"}[label]] += 1
        length_of_stay = (
            str((admission.discharge_date - admission.admit_date).days)
            if admission.discharge_date is not None
            else ""
        )
        gold_rows.append(
            {
                "admission_id": admission.admission_id,
                "master_patient_id": admission.master_patient_id,
                "hospital": admission.hospital,
                "admit_date": admission.admit_date.isoformat(),
                "discharge_date": (
                    admission.discharge_date.isoformat()
                    if admission.discharge_date is not None
                    else ""
                ),
                "age_at_admit": str(_age_at(patient.date_of_birth, admission.admit_date)),
                "sex": patient.sex,
                "diagnosis_group": admission.diagnosis_group,
                "discharge_status": admission.discharge_status,
                "length_of_stay_days": length_of_stay,
                **history,
                **lab_features,
                "readmitted_30d": label,
                "label_status": label_status,
                "observation_end_date": config.observation_end.isoformat(),
                "feature_rule_version": config.rule_version,
            }
        )

    current_time = created_at or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise GoldError("created_at must be timezone-aware.")
    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise GoldError("run_id must be a valid UUID.") from exc
    created_text = current_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    result = GoldResult(
        rule_version=config.rule_version,
        run_id=actual_run_id,
        created_at_utc=created_text,
        observation_end_date=config.observation_end.isoformat(),
        input_rows={
            "patients": len(patient_by_id),
            "admissions": len(admission_rows),
            "lab_results": sum(len(rows) for rows in labs_by_admission.values()),
            "patient_master": len(master_by_patient),
        },
        gold_rows=len(gold_rows),
        patient_master_unique_patients=len(set(master_by_patient.values())),
        gold_unique_master_patients=len(
            {admission.master_patient_id for admission in admission_rows}
        ),
        label_counts=dict(sorted(label_counts.items())),
        label_status_counts=dict(sorted(label_status_counts.items())),
        lab_presence_counts=dict(sorted(lab_presence_counts.items())),
        output_path=str(output_path),
        audit_path=str(audit_path),
    )
    audit = {
        **asdict(result),
        "input_sha256": {
            "patients": _sha256(patient_path),
            "admissions": _sha256(admission_path),
            "lab_results": _sha256(lab_path),
            "patient_master": _sha256(master_path),
        },
        "label_definition": {
            "event": "same master patient admitted at either hospital",
            "window_days_inclusive": [0, 30],
            "death_handling": "blank label; excluded_died",
            "no_discharge_handling": "blank label; excluded_no_discharge",
            "right_censoring": "positive if observed; otherwise blank until 30 days observable",
        },
        "feature_cutoff": "index admission discharge; prior-history features use completed stays available by index admission",
        "privacy_exclusions": [
            "first_name", "last_name", "phone", "date_of_birth", "state",
            "local_patient_id", "lab_id", "next_admission_id",
        ],
        "scope_exclusions": ["model_training", "risk_scoring", "outcome_analysis"],
    }
    _write_csv(output_path, gold_rows)
    _write_json(audit_path, audit)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build PATIENTRA Gold readmission features and 30-day label."
    )
    parser.add_argument("--patients", type=Path, required=True)
    parser.add_argument("--admissions", type=Path, required=True)
    parser.add_argument("--lab-results", type=Path, required=True)
    parser.add_argument("--patient-master", type=Path, required=True)
    parser.add_argument("--observation-end", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/gold"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        observation_end = _parse_date(args.observation_end, "observation_end")
        result = build_gold(
            args.patients,
            args.admissions,
            args.lab_results,
            args.patient_master,
            args.output_dir,
            GoldConfig(observation_end=observation_end),
            overwrite=args.overwrite,
        )
    except GoldError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
