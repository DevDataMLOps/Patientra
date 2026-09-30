"""Phase 2 Silver cleaning for the official Lakeside Health Network schema.

This module standardizes source records without performing identity resolution,
readmission labeling, feature engineering, or analytics. Logs, return values, profiles,
and audit JSON contain counts and paths only; patient values remain in access-controlled,
Git-ignored CSV files.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence

from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.profiling import profile_csv


RULE_VERSION = "phase2-silver-v1"
PATIENT_COLUMNS = (
    "patient_id", "source_system", "first_name", "last_name",
    "date_of_birth", "sex", "phone", "state",
)
ADMISSION_COLUMNS = (
    "admission_id", "patient_id", "hospital", "admit_date", "discharge_date",
    "diagnosis_code", "discharge_status",
)
LAB_COLUMNS = (
    "lab_id", "admission_id", "test_name", "result_value", "unit", "result_time",
)
QUARANTINE_REASON_COLUMN = "_quarantine_reason_codes"


class SilverError(RuntimeError):
    """Raised when Silver processing cannot safely complete."""


@dataclass(frozen=True)
class SilverConfig:
    """Explicit interpretation choices required by this delivery."""

    slash_date_order: str = "reject"
    numeric_sex_codes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SilverResult:
    """Aggregate-only result; it intentionally contains no record values."""

    rule_version: str
    run_id: str
    created_at_utc: str
    source_rows: dict[str, int]
    silver_rows: dict[str, int]
    quarantine_rows: dict[str, int]
    quarantine_reason_counts: dict[str, dict[str, int]]
    transformation_counts: dict[str, dict[str, int]]
    silver_paths: dict[str, str]
    quarantine_paths: dict[str, str]
    profile_path: str
    audit_path: str


def _validate_config(config: SilverConfig) -> dict[str, str]:
    if config.slash_date_order not in {"reject", "dmy", "mdy"}:
        raise SilverError("slash_date_order must be reject, dmy, or mdy.")
    mapping: dict[str, str] = {}
    for raw, canonical in config.numeric_sex_codes:
        key = raw.strip()
        value = canonical.strip().upper()
        if not key or value not in {"M", "F"} or key in mapping:
            raise SilverError("Numeric sex mappings must be unique CODE=M or CODE=F pairs.")
        mapping[key] = value
    return mapping


def _read_bronze(path: str | Path, expected: Sequence[str]) -> tuple[Path, list[dict[str, str]]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise SilverError("Every Bronze input must be an existing regular file.")
    required_header = [*expected, *LINEAGE_COLUMNS]
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != required_header:
                raise SilverError(
                    f"Schema drift detected in {source.name}; run the metadata profile and "
                    "review the official contract before cleaning."
                )
            rows: list[dict[str, str]] = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise SilverError(f"Malformed Bronze row detected in {source.name}.")
                rows.append(dict(row))
    except SilverError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SilverError(
            f"Could not read {source.name}; no source values were included in the error."
        ) from exc
    return source, rows


def _duplicate_reasons(
    rows: Sequence[dict[str, str]], key_field: str, signature_fields: Sequence[str]
) -> list[set[str]]:
    reasons = [set() for _ in rows]
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = row[key_field].strip()
        if key:
            groups[key].append(index)
    for indices in groups.values():
        if len(indices) < 2:
            continue
        signatures = {
            tuple(rows[index][field].strip() for field in signature_fields)
            for index in indices
        }
        if len(signatures) == 1:
            for index in indices[1:]:
                reasons[index].add("duplicate_record")
        else:
            for index in indices:
                reasons[index].add("duplicate_primary_key_conflict")
    return reasons


def _parse_date(value: str, field: str, slash_order: str) -> tuple[date | None, str | None]:
    text = value.strip()
    if not text:
        return None, f"missing_{field}"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text), None
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if match:
            if slash_order == "reject":
                return None, f"unconfigured_slash_date_{field}"
            first, second, year = (int(part) for part in match.groups())
            month, day = (second, first) if slash_order == "dmy" else (first, second)
            return date(year, month, day), None
    except ValueError:
        pass
    return None, f"invalid_{field}"


def _parse_datetime(
    value: str, field: str, slash_order: str
) -> tuple[datetime | None, str | None]:
    text = value.strip()
    if not text:
        return None, f"missing_{field}"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T].+", text):
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed, None
        match = re.fullmatch(
            r"(\d{1,2})/(\d{1,2})/(\d{4})[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)",
            text,
        )
        if match:
            if slash_order == "reject":
                return None, f"unconfigured_slash_date_{field}"
            first, second, year, clock = match.groups()
            month, day = (
                (int(second), int(first)) if slash_order == "dmy"
                else (int(first), int(second))
            )
            parsed_time = datetime.fromisoformat(f"{year}-{month:02d}-{day:02d}T{clock}")
            return parsed_time, None
    except ValueError:
        pass
    return None, f"invalid_{field}"


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
        suffix = "Z"
    else:
        suffix = ""
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.replace(tzinfo=None).isoformat(timespec=timespec) + suffix


def _normalize_sex(value: str, numeric_map: dict[str, str]) -> tuple[str | None, str | None]:
    text = value.strip()
    normalized = text.casefold()
    if normalized in {"m", "male"}:
        return "M", None
    if normalized in {"f", "female"}:
        return "F", None
    if text in numeric_map:
        return numeric_map[text], None
    if re.fullmatch(r"\d+", text):
        return None, "unmapped_numeric_sex_code"
    return None, "invalid_sex"


def _normalize_icd10(value: str) -> tuple[str | None, str | None]:
    compact = re.sub(r"[.\s]", "", value).upper()
    if not re.fullmatch(r"[A-Z][0-9][0-9A-Z][0-9A-Z]{0,4}", compact):
        return None, "invalid_diagnosis_code"
    return compact[:3] + (f".{compact[3:]}" if len(compact) > 3 else ""), None


def _normalize_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return text or "0"


def _convert_lab(
    test_name: str, raw_value: str, unit: str
) -> tuple[tuple[str, str, str, str] | None, str | None]:
    test = test_name.strip().casefold()
    canonical_tests = {
        "glucose": "glucose",
        "haemoglobin": "haemoglobin",
        "hemoglobin": "haemoglobin",
        "creatinine": "creatinine",
    }
    canonical_test = canonical_tests.get(test)
    if canonical_test is None:
        return None, "unsupported_test_name"
    try:
        value = Decimal(raw_value.strip())
        if not value.is_finite() or value < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return None, "invalid_result_value"

    unit_key = unit.strip().casefold().replace("μ", "u").replace("µ", "u")
    conversions: dict[tuple[str, str], tuple[Decimal, str, str]] = {
        ("glucose", "mg/dl"): (Decimal("1"), "mg/dL", "none"),
        ("glucose", "mmol/l"): (Decimal("18.016"), "mg/dL", "mmol/L_x_18.016"),
        ("haemoglobin", "g/dl"): (Decimal("1"), "g/dL", "none"),
        ("haemoglobin", "g/l"): (Decimal("0.1"), "g/dL", "g/L_div_10"),
        ("creatinine", "mg/dl"): (Decimal("1"), "mg/dL", "none"),
        ("creatinine", "umol/l"): (
            Decimal("1") / Decimal("88.4"), "mg/dL", "umol/L_div_88.4"
        ),
    }
    conversion = conversions.get((canonical_test, unit_key))
    if conversion is None:
        return None, "unsupported_test_unit"
    factor, canonical_unit, label = conversion
    return (
        canonical_test,
        _normalize_decimal(value * factor),
        canonical_unit,
        label,
    ), None


def _lineage(row: dict[str, str]) -> dict[str, str]:
    return {column: row[column] for column in LINEAGE_COLUMNS}


def _clean_patients(
    rows: Sequence[dict[str, str]], config: SilverConfig, numeric_map: dict[str, str]
) -> tuple[list[dict[str, str]], list[tuple[dict[str, str], set[str]]]]:
    duplicate_reasons = _duplicate_reasons(rows, "patient_id", PATIENT_COLUMNS)
    accepted: list[dict[str, str]] = []
    rejected: list[tuple[dict[str, str], set[str]]] = []
    for index, row in enumerate(rows):
        reasons = set(duplicate_reasons[index])
        patient_id = row["patient_id"].strip()
        source_system = row["source_system"].strip().upper()
        if not patient_id:
            reasons.add("missing_patient_id")
        if source_system not in {"LG", "RS"}:
            reasons.add("invalid_source_system")
        elif source_system == "LG" and not re.fullmatch(r"LG-\d{6}", patient_id):
            reasons.add("patient_id_source_mismatch")
        elif source_system == "RS" and not re.fullmatch(r"RS\d{5}", patient_id):
            reasons.add("patient_id_source_mismatch")
        dob, date_reason = _parse_date(
            row["date_of_birth"], "date_of_birth", config.slash_date_order
        )
        if date_reason:
            reasons.add(date_reason)
        sex, sex_reason = _normalize_sex(row["sex"], numeric_map)
        if sex_reason:
            reasons.add(sex_reason)
        if reasons:
            rejected.append((row, reasons))
            continue
        accepted.append(
            {
                "patient_id": patient_id,
                "source_system": source_system,
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "date_of_birth": dob.isoformat(),
                "sex": sex,
                "phone": row["phone"],
                "state": row["state"],
                **_lineage(row),
            }
        )
    return accepted, rejected


def _clean_admissions(
    rows: Sequence[dict[str, str]], config: SilverConfig, valid_patient_ids: set[str]
) -> tuple[
    list[dict[str, str]],
    list[tuple[dict[str, str], set[str]]],
    dict[str, tuple[date, date | None]],
]:
    duplicate_reasons = _duplicate_reasons(rows, "admission_id", ADMISSION_COLUMNS)
    accepted: list[dict[str, str]] = []
    rejected: list[tuple[dict[str, str], set[str]]] = []
    periods: dict[str, tuple[date, date | None]] = {}
    hospital_map = {
        "lakeside general": "Lakeside General",
        "riverside specialist": "Riverside Specialist",
    }
    statuses = {"home", "transferred", "died", "still_admitted"}
    for index, row in enumerate(rows):
        reasons = set(duplicate_reasons[index])
        admission_id = row["admission_id"].strip()
        patient_id = row["patient_id"].strip()
        if not admission_id:
            reasons.add("missing_admission_id")
        if patient_id not in valid_patient_ids:
            reasons.add("unknown_patient_id")
        hospital = hospital_map.get(row["hospital"].strip().casefold())
        if hospital is None:
            reasons.add("invalid_hospital")
        status = row["discharge_status"].strip().casefold()
        if status not in statuses:
            reasons.add("invalid_discharge_status")
        admit, admit_reason = _parse_date(
            row["admit_date"], "admit_date", config.slash_date_order
        )
        if admit_reason:
            reasons.add(admit_reason)
        discharge: date | None = None
        if row["discharge_date"].strip():
            discharge, discharge_reason = _parse_date(
                row["discharge_date"], "discharge_date", config.slash_date_order
            )
            if discharge_reason:
                reasons.add(discharge_reason)
        elif status != "still_admitted":
            reasons.add("missing_discharge_date")
        if status == "still_admitted" and row["discharge_date"].strip():
            reasons.add("unexpected_discharge_date_for_still_admitted")
        if admit and discharge and discharge < admit:
            reasons.add("discharge_before_admission")
        diagnosis, diagnosis_reason = _normalize_icd10(row["diagnosis_code"])
        if diagnosis_reason:
            reasons.add(diagnosis_reason)
        if reasons:
            rejected.append((row, reasons))
            continue
        accepted.append(
            {
                "admission_id": admission_id,
                "patient_id": patient_id,
                "hospital": hospital,
                "admit_date": admit.isoformat(),
                "discharge_date": discharge.isoformat() if discharge else "",
                "diagnosis_code": diagnosis,
                "discharge_status": status,
                **_lineage(row),
            }
        )
        periods[admission_id] = (admit, discharge)
    return accepted, rejected, periods


def _clean_labs(
    rows: Sequence[dict[str, str]], config: SilverConfig,
    admission_periods: dict[str, tuple[date, date | None]],
) -> tuple[list[dict[str, str]], list[tuple[dict[str, str], set[str]]]]:
    duplicate_reasons = _duplicate_reasons(rows, "lab_id", LAB_COLUMNS)
    accepted: list[dict[str, str]] = []
    rejected: list[tuple[dict[str, str], set[str]]] = []
    for index, row in enumerate(rows):
        reasons = set(duplicate_reasons[index])
        lab_id = row["lab_id"].strip()
        admission_id = row["admission_id"].strip()
        if not lab_id:
            reasons.add("missing_lab_id")
        period = admission_periods.get(admission_id)
        if period is None:
            reasons.add("unknown_admission_id")
        converted, conversion_reason = _convert_lab(
            row["test_name"], row["result_value"], row["unit"]
        )
        if conversion_reason:
            reasons.add(conversion_reason)
        result_time, time_reason = _parse_datetime(
            row["result_time"], "result_time", config.slash_date_order
        )
        if time_reason:
            reasons.add(time_reason)
        if period and result_time:
            admit, discharge = period
            if result_time.date() < admit:
                reasons.add("result_before_admission")
            if discharge and result_time.date() > discharge:
                reasons.add("result_after_discharge")
        if reasons:
            rejected.append((row, reasons))
            continue
        test, value, unit, conversion = converted
        accepted.append(
            {
                "lab_id": lab_id,
                "admission_id": admission_id,
                "test_name": test,
                "result_value": value,
                "unit": unit,
                "result_time": _format_datetime(result_time),
                "result_value_original": row["result_value"],
                "unit_original": row["unit"],
                "conversion_applied": conversion,
                **_lineage(row),
            }
        )
    return accepted, rejected


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_csv(
    path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent,
        prefix=".tmp-", suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
        _restrict(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=".tmp-", suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
        _restrict(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _reason_counts(
    rejected: Sequence[tuple[dict[str, str], set[str]]]
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for _, reasons in rejected:
        counter.update(reasons)
    return dict(sorted(counter.items()))


def _quarantine_rows(
    rejected: Sequence[tuple[dict[str, str], set[str]]]
) -> Iterable[dict[str, str]]:
    for row, reasons in rejected:
        yield {**row, QUARANTINE_REASON_COLUMN: ";".join(sorted(reasons))}


def _lineage_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row[column] for column in LINEAGE_COLUMNS)


def _transformation_counts(
    patient_rows: Sequence[dict[str, str]],
    admission_rows: Sequence[dict[str, str]],
    clean_patients: Sequence[dict[str, str]],
    clean_admissions: Sequence[dict[str, str]],
    clean_labs: Sequence[dict[str, str]],
) -> dict[str, dict[str, int]]:
    accepted_patient_keys = {_lineage_key(row) for row in clean_patients}
    accepted_admission_keys = {_lineage_key(row) for row in clean_admissions}
    sex_counts = Counter(row["sex"] for row in clean_patients)
    lab_conversion_counts = Counter(row["conversion_applied"] for row in clean_labs)
    patients_slash_dates = sum(
        1
        for row in patient_rows
        if _lineage_key(row) in accepted_patient_keys and "/" in row["date_of_birth"]
    )
    admissions_slash_dates = sum(
        1
        for row in admission_rows
        if _lineage_key(row) in accepted_admission_keys and "/" in row["admit_date"]
    )
    diagnosis_reformatted = 0
    for row in admission_rows:
        if _lineage_key(row) not in accepted_admission_keys:
            continue
        normalized, _ = _normalize_icd10(row["diagnosis_code"])
        if normalized != row["diagnosis_code"].strip():
            diagnosis_reformatted += 1
    return {
        "patients": {
            "date_of_birth_slash_to_iso": patients_slash_dates,
            "sex_F": sex_counts["F"],
            "sex_M": sex_counts["M"],
        },
        "admissions": {
            "admit_date_slash_to_iso": admissions_slash_dates,
            "diagnosis_code_reformatted": diagnosis_reformatted,
        },
        "lab_results": dict(sorted(lab_conversion_counts.items())),
    }


def build_silver(
    patients_bronze: str | Path,
    admissions_bronze: str | Path,
    labs_bronze: str | Path,
    silver_dir: str | Path,
    quarantine_dir: str | Path,
    *,
    config: SilverConfig | None = None,
    overwrite: bool = False,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> SilverResult:
    """Build deterministic Silver CSVs plus reason-coded quarantine and aggregate audit."""
    selected = config or SilverConfig()
    numeric_map = _validate_config(selected)
    patients_path, patient_rows = _read_bronze(patients_bronze, PATIENT_COLUMNS)
    admissions_path, admission_rows = _read_bronze(admissions_bronze, ADMISSION_COLUMNS)
    labs_path, lab_rows = _read_bronze(labs_bronze, LAB_COLUMNS)

    clean_patients, rejected_patients = _clean_patients(patient_rows, selected, numeric_map)
    valid_patient_ids = {row["patient_id"] for row in clean_patients}
    clean_admissions, rejected_admissions, admission_periods = _clean_admissions(
        admission_rows, selected, valid_patient_ids
    )
    clean_labs, rejected_labs = _clean_labs(lab_rows, selected, admission_periods)

    silver_root = Path(silver_dir).expanduser().resolve()
    quarantine_root = Path(quarantine_dir).expanduser().resolve()
    silver_paths = {
        "patients": silver_root / "patients.silver.csv",
        "admissions": silver_root / "admissions.silver.csv",
        "lab_results": silver_root / "lab_results.silver.csv",
    }
    quarantine_paths = {
        "patients": quarantine_root / "patients.quarantine.csv",
        "admissions": quarantine_root / "admissions.quarantine.csv",
        "lab_results": quarantine_root / "lab_results.quarantine.csv",
    }
    profile_path = silver_root / "schema_profile.json"
    audit_path = silver_root / "silver_audit.json"
    planned = [*silver_paths.values(), *quarantine_paths.values(), profile_path, audit_path]
    inputs = {patients_path, admissions_path, labs_path}
    if inputs.intersection(planned):
        raise SilverError("Silver outputs must not overwrite Bronze inputs.")
    if not overwrite and any(path.exists() for path in planned):
        raise SilverError("A Silver output exists; use overwrite=True intentionally.")

    patient_fields = [*PATIENT_COLUMNS, *LINEAGE_COLUMNS]
    admission_fields = [*ADMISSION_COLUMNS, *LINEAGE_COLUMNS]
    lab_fields = [
        *LAB_COLUMNS, "result_value_original", "unit_original", "conversion_applied",
        *LINEAGE_COLUMNS,
    ]
    _write_csv(silver_paths["patients"], patient_fields, clean_patients)
    _write_csv(silver_paths["admissions"], admission_fields, clean_admissions)
    _write_csv(silver_paths["lab_results"], lab_fields, clean_labs)
    _write_csv(
        quarantine_paths["patients"],
        [*PATIENT_COLUMNS, *LINEAGE_COLUMNS, QUARANTINE_REASON_COLUMN],
        _quarantine_rows(rejected_patients),
    )
    _write_csv(
        quarantine_paths["admissions"],
        [*ADMISSION_COLUMNS, *LINEAGE_COLUMNS, QUARANTINE_REASON_COLUMN],
        _quarantine_rows(rejected_admissions),
    )
    _write_csv(
        quarantine_paths["lab_results"],
        [*LAB_COLUMNS, *LINEAGE_COLUMNS, QUARANTINE_REASON_COLUMN],
        _quarantine_rows(rejected_labs),
    )

    profiles = {
        "profile_version": "1.0",
        "files": [profile_csv(path) for path in (patients_path, admissions_path, labs_path)],
    }
    _write_json(profile_path, profiles)

    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_rows = {
        "patients": len(patient_rows),
        "admissions": len(admission_rows),
        "lab_results": len(lab_rows),
    }
    silver_rows = {
        "patients": len(clean_patients),
        "admissions": len(clean_admissions),
        "lab_results": len(clean_labs),
    }
    quarantine_rows = {
        "patients": len(rejected_patients),
        "admissions": len(rejected_admissions),
        "lab_results": len(rejected_labs),
    }
    reason_counts = {
        "patients": _reason_counts(rejected_patients),
        "admissions": _reason_counts(rejected_admissions),
        "lab_results": _reason_counts(rejected_labs),
    }
    transformation_counts = _transformation_counts(
        patient_rows, admission_rows, clean_patients, clean_admissions, clean_labs
    )
    for dataset in source_rows:
        if source_rows[dataset] != silver_rows[dataset] + quarantine_rows[dataset]:
            raise SilverError(f"Internal reconciliation failed for {dataset}.")
    result = SilverResult(
        rule_version=RULE_VERSION,
        run_id=run_id or str(uuid.uuid4()),
        created_at_utc=timestamp.isoformat().replace("+00:00", "Z"),
        source_rows=source_rows,
        silver_rows=silver_rows,
        quarantine_rows=quarantine_rows,
        quarantine_reason_counts=reason_counts,
        transformation_counts=transformation_counts,
        silver_paths={key: str(value) for key, value in silver_paths.items()},
        quarantine_paths={key: str(value) for key, value in quarantine_paths.items()},
        profile_path=str(profile_path),
        audit_path=str(audit_path),
    )
    audit = {
        **asdict(result),
        "configuration": {
            "slash_date_order": selected.slash_date_order,
            "numeric_sex_codes": dict(selected.numeric_sex_codes),
        },
        "scope_exclusions": [
            "identity_resolution", "patient_master", "review_queue",
            "readmission_labels", "feature_engineering", "readmission_analytics",
        ],
        "reconciliation_passed": True,
    }
    _write_json(audit_path, audit)
    return result


def _parse_numeric_sex_codes(values: Sequence[str]) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise SilverError("--numeric-sex-code must use CODE=M or CODE=F.")
        raw, canonical = value.split("=", 1)
        parsed.append((raw, canonical))
    return tuple(parsed)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build PATIENTRA Phase 2 Silver tables.")
    parser.add_argument("--patients", type=Path, required=True, help="Patients Bronze CSV")
    parser.add_argument("--admissions", type=Path, required=True, help="Admissions Bronze CSV")
    parser.add_argument("--lab-results", type=Path, required=True, help="Lab-results Bronze CSV")
    parser.add_argument("--silver-dir", type=Path, default=Path("data/silver"))
    parser.add_argument(
        "--quarantine-dir", type=Path, default=Path("data/quarantine/silver")
    )
    parser.add_argument(
        "--slash-date-order", choices=("reject", "dmy", "mdy"), default="reject"
    )
    parser.add_argument(
        "--numeric-sex-code", action="append", default=[], metavar="CODE=M",
        help="Explicit owner-approved numeric sex mapping; repeat for each code.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = SilverConfig(
            slash_date_order=args.slash_date_order,
            numeric_sex_codes=_parse_numeric_sex_codes(args.numeric_sex_code),
        )
        result = build_silver(
            args.patients, args.admissions, args.lab_results,
            args.silver_dir, args.quarantine_dir,
            config=config, overwrite=args.overwrite,
        )
    except SilverError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
