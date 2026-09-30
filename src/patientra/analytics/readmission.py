"""Privacy-conscious Phase 5 aggregate readmission analytics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from patientra.features.gold import GOLD_FIELDS


RULE_VERSION = "phase5-analytics-v1"
ELIGIBLE_STATUSES = {
    "labeled_positive": "1",
    "labeled_negative": "0",
}
EXCLUDED_STATUSES = {
    "excluded_died",
    "excluded_no_discharge",
    "censored_incomplete_30d_followup",
}
HOSPITALS = {"Lakeside General", "Riverside Specialist"}
DISCHARGE_STATUSES = {"home", "transferred", "died", "still_admitted"}
DIAGNOSIS_GROUP_PATTERN = re.compile(r"^[A-Z][0-9]{2}$")
BREAKDOWN_FIELDS = (
    "dimension",
    "category",
    "eligible_admissions",
    "readmitted_admissions",
    "not_readmitted_admissions",
    "readmission_rate_pct",
    "wilson_95_lower_pct",
    "wilson_95_upper_pct",
    "suppression_reason",
)


class AnalyticsError(RuntimeError):
    """Raised when aggregate analytics cannot be produced safely."""


@dataclass(frozen=True)
class AnalyticsConfig:
    """Versioned configuration for aggregate release controls."""

    minimum_cell_size: int = 11
    rule_version: str = RULE_VERSION


@dataclass(frozen=True)
class AnalyticsResult:
    """Aggregate-only run result containing no patient or admission identifiers."""

    rule_version: str
    run_id: str
    created_at_utc: str
    input_rows: int
    eligible_rows: int
    excluded_rows: int
    breakdown_dimensions: int
    breakdown_rows: int
    suppressed_breakdown_rows: int
    report_path: str
    breakdown_path: str
    audit_path: str


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
        raise AnalyticsError(f"{field} must contain ISO YYYY-MM-DD dates.") from exc
    if parsed.isoformat() != value:
        raise AnalyticsError(f"{field} must contain canonical ISO YYYY-MM-DD dates.")
    return parsed


def _parse_int(value: str, field: str, minimum: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AnalyticsError(f"{field} must contain an integer.") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise AnalyticsError(f"{field} is outside the supported range.")
    return parsed


def _read_gold(path: str | Path) -> tuple[Path, list[dict[str, str]]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise AnalyticsError("The Gold input must be an existing regular file.")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(GOLD_FIELDS):
                raise AnalyticsError("The Gold schema does not match the Phase 5 contract.")
            rows = list(reader)
    except AnalyticsError:
        raise
    except (csv.Error, UnicodeError, OSError) as exc:
        raise AnalyticsError("The Gold input could not be read safely.") from exc
    if not rows:
        raise AnalyticsError("The Gold input must contain at least one row.")
    return source, rows


def _validate_rows(rows: Sequence[dict[str, str]]) -> None:
    seen_admissions: set[str] = set()
    observation_ends: set[str] = set()
    feature_versions: set[str] = set()
    for row in rows:
        admission_id = row["admission_id"]
        if not admission_id or admission_id in seen_admissions:
            raise AnalyticsError("Gold contains a blank or duplicate admission_id.")
        seen_admissions.add(admission_id)
        if not row["master_patient_id"]:
            raise AnalyticsError("Gold contains a blank master_patient_id.")
        if row["hospital"] not in HOSPITALS:
            raise AnalyticsError("Gold contains an unsupported hospital.")
        if row["sex"] not in {"M", "F"}:
            raise AnalyticsError("Gold contains a noncanonical sex value.")
        if not DIAGNOSIS_GROUP_PATTERN.fullmatch(row["diagnosis_group"]):
            raise AnalyticsError("Gold contains an invalid diagnosis_group.")
        if row["discharge_status"] not in DISCHARGE_STATUSES:
            raise AnalyticsError("Gold contains an invalid discharge_status.")
        admit_date = _parse_date(row["admit_date"], "admit_date")
        discharge_date = (
            _parse_date(row["discharge_date"], "discharge_date")
            if row["discharge_date"]
            else None
        )
        if discharge_date is not None and discharge_date < admit_date:
            raise AnalyticsError("Gold contains invalid stay chronology.")
        if row["discharge_status"] == "still_admitted" and discharge_date is not None:
            raise AnalyticsError("A still-admitted Gold row has a discharge date.")
        if row["discharge_status"] != "still_admitted" and discharge_date is None:
            raise AnalyticsError("A completed Gold row has no discharge date.")
        _parse_int(row["age_at_admit"], "age_at_admit", 0, 120)
        if discharge_date is None:
            if row["length_of_stay_days"]:
                raise AnalyticsError("A no-discharge Gold row has a length of stay.")
        else:
            length_of_stay = _parse_int(
                row["length_of_stay_days"], "length_of_stay_days", 0
            )
            if length_of_stay != (discharge_date - admit_date).days:
                raise AnalyticsError("Gold length_of_stay_days is inconsistent.")
        _parse_int(
            row["prior_completed_admission_count"],
            "prior_completed_admission_count",
            0,
        )
        status = row["label_status"]
        label = row["readmitted_30d"]
        if status in ELIGIBLE_STATUSES:
            if label != ELIGIBLE_STATUSES[status]:
                raise AnalyticsError("Gold label and label_status are inconsistent.")
            if row["discharge_status"] not in {"home", "transferred"}:
                raise AnalyticsError("An eligible Gold row has an excluded discharge status.")
        elif status in EXCLUDED_STATUSES:
            if label:
                raise AnalyticsError("An excluded Gold row must have a blank label.")
            if status == "excluded_died" and row["discharge_status"] != "died":
                raise AnalyticsError("Death exclusion conflicts with discharge_status.")
            if (
                status == "excluded_no_discharge"
                and row["discharge_status"] != "still_admitted"
            ):
                raise AnalyticsError("No-discharge exclusion conflicts with discharge_status.")
        else:
            raise AnalyticsError("Gold contains an unsupported label_status.")
        observation_end = row["observation_end_date"]
        _parse_date(observation_end, "observation_end_date")
        observation_ends.add(observation_end)
        if not row["feature_rule_version"]:
            raise AnalyticsError("Gold contains a blank feature_rule_version.")
        feature_versions.add(row["feature_rule_version"])
    if len(observation_ends) != 1 or len(feature_versions) != 1:
        raise AnalyticsError("Gold mixes observation ends or feature rule versions.")


def _wilson_interval(positive: int, total: int) -> tuple[float, float]:
    proportion = positive / total
    z = 1.96
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return round(100 * (center - margin), 2), round(100 * (center + margin), 2)


def _metrics(positive: int, negative: int) -> dict[str, int | float]:
    total = positive + negative
    lower, upper = _wilson_interval(positive, total)
    return {
        "eligible_admissions": total,
        "readmitted_admissions": positive,
        "not_readmitted_admissions": negative,
        "readmission_rate_pct": round(100 * positive / total, 2),
        "wilson_95_lower_pct": lower,
        "wilson_95_upper_pct": upper,
    }


def _age_band(row: dict[str, str]) -> str:
    age = int(row["age_at_admit"])
    if age <= 17:
        return "00-17"
    if age <= 34:
        return "18-34"
    if age <= 49:
        return "35-49"
    if age <= 64:
        return "50-64"
    if age <= 79:
        return "65-79"
    return "80+"


def _stay_band(row: dict[str, str]) -> str:
    days = int(row["length_of_stay_days"])
    if days == 0:
        return "0"
    if days <= 3:
        return "1-3"
    if days <= 7:
        return "4-7"
    if days <= 14:
        return "8-14"
    return "15+"


def _prior_band(row: dict[str, str]) -> str:
    count = int(row["prior_completed_admission_count"])
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    return "2+"


BREAKDOWNS: tuple[tuple[str, Callable[[dict[str, str]], str]], ...] = (
    ("hospital", lambda row: row["hospital"]),
    ("sex", lambda row: row["sex"]),
    ("age_band", _age_band),
    ("diagnosis_group", lambda row: row["diagnosis_group"]),
    ("discharge_status", lambda row: row["discharge_status"]),
    ("prior_completed_admission_band", _prior_band),
    ("length_of_stay_band", _stay_band),
    ("discharge_year", lambda row: row["discharge_date"][:4]),
    ("discharge_month", lambda row: row["discharge_date"][:7]),
)


def _breakdown(
    rows: Sequence[dict[str, str]],
    dimension: str,
    extractor: Callable[[dict[str, str]], str],
    minimum_cell_size: int,
) -> list[dict[str, object]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        groups[extractor(row)][row["readmitted_30d"]] += 1
    reasons: dict[str, str] = {}
    for category, counts in groups.items():
        positive = counts["1"]
        negative = counts["0"]
        if (
            positive + negative < minimum_cell_size
            or positive < minimum_cell_size
            or negative < minimum_cell_size
        ):
            reasons[category] = "primary_small_cell"
    if len(reasons) == 1 and len(groups) > 1:
        candidates = [
            (
                counts["1"] + counts["0"],
                counts["1"],
                category,
            )
            for category, counts in groups.items()
            if category not in reasons
        ]
        if candidates:
            reasons[min(candidates)[2]] = "complementary_suppression"
    output: list[dict[str, object]] = []
    for category in sorted(groups):
        counts = groups[category]
        positive = counts["1"]
        negative = counts["0"]
        reason = reasons.get(category, "")
        row: dict[str, object] = {
            "dimension": dimension,
            "category": category,
            "suppression_reason": reason,
        }
        if reason:
            row.update(
                {
                    "eligible_admissions": None,
                    "readmitted_admissions": None,
                    "not_readmitted_admissions": None,
                    "readmission_rate_pct": None,
                    "wilson_95_lower_pct": None,
                    "wilson_95_upper_pct": None,
                }
            )
        else:
            row.update(_metrics(positive, negative))
        output.append(row)
    return output


def _excluded_statuses(
    excluded: Counter[str], minimum_cell_size: int
) -> list[dict[str, object]]:
    reasons = {
        status: "primary_small_cell"
        for status, count in excluded.items()
        if count < minimum_cell_size
    }
    if len(reasons) == 1 and len(excluded) > 1:
        candidates = [
            (count, status) for status, count in excluded.items() if status not in reasons
        ]
        reasons[min(candidates)[1]] = "complementary_suppression"
    return [
        {
            "label_status": status,
            "admissions": None if status in reasons else excluded[status],
            "suppression_reason": reasons.get(status, ""),
        }
        for status in sorted(excluded)
    ]


def _write_json(path: Path, payload: object) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise AnalyticsError("An analytics JSON output could not be written atomically.") from exc


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=BREAKDOWN_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise AnalyticsError("The analytics CSV output could not be written atomically.") from exc


def build_analytics(
    gold: str | Path,
    output_dir: str | Path,
    config: AnalyticsConfig = AnalyticsConfig(),
    *,
    overwrite: bool = False,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> AnalyticsResult:
    """Build suppressed aggregate readmission analytics from Phase 4 Gold."""

    if config.minimum_cell_size < 1:
        raise AnalyticsError("minimum_cell_size must be at least 1.")
    gold_path, rows = _read_gold(gold)
    _validate_rows(rows)
    eligible = [row for row in rows if row["label_status"] in ELIGIBLE_STATUSES]
    positive = sum(row["readmitted_30d"] == "1" for row in eligible)
    negative = sum(row["readmitted_30d"] == "0" for row in eligible)
    eligible_master_patients = len(
        {row["master_patient_id"] for row in eligible}
    )
    if min(
        len(eligible), positive, negative, eligible_master_patients
    ) < config.minimum_cell_size:
        raise AnalyticsError("The overall cohort does not satisfy minimum_cell_size.")
    excluded = Counter(
        row["label_status"] for row in rows if row["label_status"] in EXCLUDED_STATUSES
    )

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "readmission_analytics.json"
    breakdown_path = output_root / "readmission_breakdowns.csv"
    audit_path = output_root / "readmission_analytics_audit.json"
    if not overwrite and any(path.exists() for path in (report_path, breakdown_path, audit_path)):
        raise AnalyticsError(
            "Analytics outputs already exist; use --overwrite for an intentional rerun."
        )

    breakdowns: dict[str, list[dict[str, object]]] = {}
    flat_breakdowns: list[dict[str, object]] = []
    for dimension, extractor in BREAKDOWNS:
        dimension_rows = _breakdown(
            eligible, dimension, extractor, config.minimum_cell_size
        )
        breakdowns[dimension] = dimension_rows
        flat_breakdowns.extend(dimension_rows)

    report = {
        "analytics_rule_version": config.rule_version,
        "gold_feature_rule_version": rows[0]["feature_rule_version"],
        "observation_end_date": rows[0]["observation_end_date"],
        "minimum_cell_size": config.minimum_cell_size,
        "cohort": {
            "gold_admissions": len(rows),
            "eligible_admissions": len(eligible),
            "excluded_admissions": len(rows) - len(eligible),
            "eligible_master_patients": eligible_master_patients,
            "excluded_statuses": _excluded_statuses(
                excluded, config.minimum_cell_size
            ),
        },
        "overall": _metrics(positive, negative),
        "breakdowns": breakdowns,
        "interpretation_boundary": (
            "Descriptive admission-level association only; no causal, clinical, or "
            "patient-level risk conclusion."
        ),
    }
    current_time = created_at or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise AnalyticsError("created_at must be timezone-aware.")
    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise AnalyticsError("run_id must be a valid UUID.") from exc
    created_text = current_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(report_path, report)
    _write_csv(breakdown_path, flat_breakdowns)
    result = AnalyticsResult(
        rule_version=config.rule_version,
        run_id=actual_run_id,
        created_at_utc=created_text,
        input_rows=len(rows),
        eligible_rows=len(eligible),
        excluded_rows=len(rows) - len(eligible),
        breakdown_dimensions=len(BREAKDOWNS),
        breakdown_rows=len(flat_breakdowns),
        suppressed_breakdown_rows=sum(
            bool(row["suppression_reason"]) for row in flat_breakdowns
        ),
        report_path=str(report_path),
        breakdown_path=str(breakdown_path),
        audit_path=str(audit_path),
    )
    audit = {
        **asdict(result),
        "gold_input_sha256": _sha256(gold_path),
        "output_sha256": {
            "readmission_analytics.json": _sha256(report_path),
            "readmission_breakdowns.csv": _sha256(breakdown_path),
        },
        "release_controls": {
            "minimum_cell_size": config.minimum_cell_size,
            "primary_suppression": "denominator, positive, or negative count below threshold",
            "complementary_suppression": "applied when exactly one group is primarily suppressed",
        },
        "privacy_exclusions": [
            "admission_id",
            "master_patient_id",
            "names",
            "phone",
            "local_patient_id",
            "date_of_birth",
            "lab_id",
        ],
        "scope_exclusions": [
            "patient_level_output",
            "causal_inference",
            "clinical_recommendation",
            "model_training",
            "risk_scoring",
        ],
    }
    _write_json(audit_path, audit)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build privacy-safe aggregate PATIENTRA readmission analytics."
    )
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/phase5"))
    parser.add_argument("--minimum-cell-size", type=int, default=11)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_analytics(
            args.gold,
            args.output_dir,
            AnalyticsConfig(minimum_cell_size=args.minimum_cell_size),
            overwrite=args.overwrite,
        )
    except AnalyticsError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
