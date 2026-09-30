"""Aggregate-only PATIENTRA Core MVP result calculation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence, cast

from patientra.features.gold import GOLD_FIELDS
from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.transformations.silver import ADMISSION_COLUMNS


RULE_VERSION = "patientra-core-mvp-v1"
SILVER_ADMISSION_FIELDS = (*ADMISSION_COLUMNS, *LINEAGE_COLUMNS)
ELIGIBLE_STATUSES = {
    "labeled_positive": "1",
    "labeled_negative": "0",
}


class CoreMvpError(RuntimeError):
    """Raised when the Core MVP answers cannot be calculated safely."""


@dataclass(frozen=True)
class CoreMvpResult:
    """Aggregate-only result containing no patient or admission identifiers."""

    rule_version: str
    eligible_admissions: int
    before_matching_rate_pct: float
    after_matching_rate_pct: float
    hidden_readmissions: int
    highest_diagnosis_group: str
    highest_diagnosis_rate_pct: float
    automatic_matches: int
    review_candidates: int
    output_path: str


@dataclass(frozen=True)
class _Admission:
    admission_id: str
    patient_id: str
    admit_date: date
    discharge_date: date | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path, label: str) -> tuple[Path, dict[str, object]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise CoreMvpError(f"The {label} input must be an existing regular file.")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoreMvpError(f"The {label} input is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise CoreMvpError(f"The {label} input must contain a JSON object.")
    return source, value


def _read_csv(
    path: str | Path,
    fields: Sequence[str],
    label: str,
) -> tuple[Path, list[dict[str, str]]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise CoreMvpError(f"The {label} input must be an existing regular file.")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(fields):
                raise CoreMvpError(f"The {label} schema does not match its contract.")
            rows = list(reader)
    except CoreMvpError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CoreMvpError(f"The {label} input could not be read safely.") from exc
    if not rows:
        raise CoreMvpError(f"The {label} input must contain at least one row.")
    return source, rows


def _parse_date(value: str, field: str, *, allow_blank: bool = False) -> date | None:
    if allow_blank and value == "":
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CoreMvpError(f"{field} must contain canonical ISO YYYY-MM-DD dates.") from exc
    if parsed.isoformat() != value:
        raise CoreMvpError(f"{field} must contain canonical ISO YYYY-MM-DD dates.")
    return parsed


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CoreMvpError(f"{field} must contain an integer of at least {minimum}.")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreMvpError(f"{field} must contain a numeric value.")
    return float(value)


def _rate(positive: int, total: int) -> float:
    if total <= 0:
        raise CoreMvpError("The eligible cohort must contain at least one admission.")
    value = (Decimal(positive) * Decimal("100") / Decimal(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(value)


def _admissions(rows: Sequence[dict[str, str]]) -> tuple[
    dict[str, _Admission], dict[str, list[_Admission]]
]:
    by_id: dict[str, _Admission] = {}
    by_patient: dict[str, list[_Admission]] = defaultdict(list)
    for row in rows:
        admission_id = row["admission_id"]
        patient_id = row["patient_id"]
        if not admission_id or admission_id in by_id:
            raise CoreMvpError("Silver admissions contain a blank or duplicate admission_id.")
        if not patient_id:
            raise CoreMvpError("Silver admissions contain a blank patient_id.")
        admission = _Admission(
            admission_id=admission_id,
            patient_id=patient_id,
            admit_date=_parse_date(row["admit_date"], "admit_date"),
            discharge_date=_parse_date(
                row["discharge_date"], "discharge_date", allow_blank=True
            ),
        )
        by_id[admission_id] = admission
        by_patient[patient_id].append(admission)
    return by_id, by_patient


def _matching_impact(
    gold_rows: Sequence[dict[str, str]],
    admissions_by_id: dict[str, _Admission],
    admissions_by_patient: dict[str, list[_Admission]],
) -> dict[str, object]:
    observation_ends = {row["observation_end_date"] for row in gold_rows}
    if len(observation_ends) != 1:
        raise CoreMvpError("Gold must contain one observation_end_date.")
    observation_end = _parse_date(observation_ends.pop(), "observation_end_date")
    seen: set[str] = set()
    eligible = 0
    before_positive = 0
    after_positive = 0
    local_positive_master_negative = 0

    for row in gold_rows:
        admission_id = row["admission_id"]
        if not admission_id or admission_id in seen:
            raise CoreMvpError("Gold contains a blank or duplicate admission_id.")
        seen.add(admission_id)
        source = admissions_by_id.get(admission_id)
        if source is None:
            raise CoreMvpError("Every Gold admission must join to Silver admissions.")
        if row["admit_date"] != source.admit_date.isoformat():
            raise CoreMvpError("Gold and Silver admission dates do not reconcile.")
        if source.discharge_date is not None:
            if row["discharge_date"] != source.discharge_date.isoformat():
                raise CoreMvpError("Gold and Silver discharge dates do not reconcile.")
        elif row["discharge_date"]:
            raise CoreMvpError("Gold and Silver discharge dates do not reconcile.")

        status = row["label_status"]
        if status not in ELIGIBLE_STATUSES:
            continue
        expected_label = ELIGIBLE_STATUSES[status]
        if row["readmitted_30d"] != expected_label:
            raise CoreMvpError("Gold labels are inconsistent with label_status.")
        if source.discharge_date is None:
            raise CoreMvpError("An eligible Gold admission must have a discharge date.")

        eligible += 1
        local_positive = any(
            candidate.admission_id != source.admission_id
            and candidate.admit_date >= source.discharge_date
            and candidate.admit_date <= observation_end
            and 0 <= (candidate.admit_date - source.discharge_date).days <= 30
            for candidate in admissions_by_patient[source.patient_id]
        )
        master_positive = row["readmitted_30d"] == "1"
        before_positive += int(local_positive)
        after_positive += int(master_positive)
        local_positive_master_negative += int(local_positive and not master_positive)

    if local_positive_master_negative:
        raise CoreMvpError(
            "Master-identity labels must not lose a local-ID readmission."
        )
    if after_positive < before_positive:
        raise CoreMvpError("After-matching positives cannot be below before-matching positives.")

    before_rate = _rate(before_positive, eligible)
    after_rate = _rate(after_positive, eligible)
    return {
        "eligible_admissions": eligible,
        "before_identity_matching": {
            "readmitted_admissions": before_positive,
            "readmission_rate_pct": before_rate,
        },
        "after_identity_matching": {
            "readmitted_admissions": after_positive,
            "readmission_rate_pct": after_rate,
        },
        "hidden_cross_hospital_readmissions": after_positive - before_positive,
        "percentage_point_change": round(after_rate - before_rate, 2),
    }


def _diagnosis_result(
    report: dict[str, object], gold_rows: Sequence[dict[str, str]]
) -> dict[str, object]:
    breakdowns = report.get("breakdowns")
    if not isinstance(breakdowns, dict):
        raise CoreMvpError("Analytics report breakdowns are missing.")
    diagnoses = breakdowns.get("diagnosis_group")
    if not isinstance(diagnoses, list) or not all(isinstance(row, dict) for row in diagnoses):
        raise CoreMvpError("Analytics diagnosis breakdown is malformed.")
    eligible_counts: Counter[str] = Counter()
    positive_counts: Counter[str] = Counter()
    for gold_row in gold_rows:
        if gold_row["label_status"] not in ELIGIBLE_STATUSES:
            continue
        diagnosis_group = gold_row["diagnosis_group"]
        eligible_counts[diagnosis_group] += 1
        positive_counts[diagnosis_group] += int(gold_row["readmitted_30d"] == "1")
    released: list[dict[str, object]] = []
    for row in diagnoses:
        if row.get("suppression_reason"):
            continue
        category = row.get("category")
        if not isinstance(category, str) or not category:
            raise CoreMvpError("A released diagnosis category is invalid.")
        eligible = _integer(
            row.get("eligible_admissions"),
            "diagnosis eligible_admissions",
            minimum=1,
        )
        positive = _integer(
            row.get("readmitted_admissions"), "diagnosis readmitted_admissions"
        )
        rate = _number(
            row.get("readmission_rate_pct"), "diagnosis readmission_rate_pct"
        )
        if (
            eligible_counts[category] != eligible
            or positive_counts[category] != positive
            or _rate(positive, eligible) != rate
        ):
            raise CoreMvpError(
                "A released diagnosis result does not reconcile to Gold."
            )
        released.append(
            {
                "diagnosis_group": category,
                "eligible_admissions": eligible,
                "readmitted_admissions": positive,
                "readmission_rate_pct": rate,
            }
        )
    if not released:
        raise CoreMvpError("Analytics contains no released diagnosis-group results.")
    return sorted(
        released,
        key=lambda row: (-float(row["readmission_rate_pct"]), str(row["diagnosis_group"])),
    )[0]


def _identity_result(audit: dict[str, object]) -> dict[str, object]:
    auto = _integer(audit.get("auto_matches"), "auto_matches")
    review = _integer(audit.get("review_candidates"), "review_candidates")
    accepted = _integer(audit.get("human_accepted_matches"), "human_accepted_matches")
    statuses = audit.get("review_status_counts")
    if not isinstance(statuses, dict):
        raise CoreMvpError("Identity review_status_counts are missing.")
    accepted_status = _integer(statuses.get("ACCEPTED", 0), "review ACCEPTED count")
    rejected_status = _integer(statuses.get("REJECTED", 0), "review REJECTED count")
    abstained_status = _integer(statuses.get("ABSTAINED", 0), "review ABSTAINED count")
    pending = review - accepted_status - rejected_status - abstained_status
    if accepted != accepted_status or pending < 0:
        raise CoreMvpError("Identity review counts do not reconcile.")
    return {
        "automatic_matches": auto,
        "sent_for_human_review": review,
        "human_review_outcomes": {
            "accepted": accepted_status,
            "rejected": rejected_status,
            "abstained": abstained_status,
            "pending": pending,
        },
    }


def _validate_analytics_reconciliation(
    report: dict[str, object], matching: dict[str, object]
) -> None:
    overall = report.get("overall")
    if not isinstance(overall, dict):
        raise CoreMvpError("Analytics overall results are missing.")
    after_value = matching["after_identity_matching"]
    if not isinstance(after_value, dict):
        raise CoreMvpError("After-matching results are malformed.")
    after = cast(dict[str, object], after_value)
    if (
        _integer(overall.get("eligible_admissions"), "analytics eligible_admissions", minimum=1)
        != matching["eligible_admissions"]
        or _integer(overall.get("readmitted_admissions"), "analytics readmitted_admissions")
        != after["readmitted_admissions"]
        or _number(
            overall.get("readmission_rate_pct"), "analytics readmission_rate_pct"
        )
        != after["readmission_rate_pct"]
    ):
        raise CoreMvpError("Core MVP results do not reconcile to Phase 5 analytics.")


def _write_json(path: Path, payload: object) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
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
        raise CoreMvpError("The Core MVP report could not be written atomically.") from exc


def build_core_mvp(
    silver_admissions: str | Path,
    gold: str | Path,
    identity_audit: str | Path,
    analytics_report: str | Path,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> CoreMvpResult:
    """Calculate the three aggregate PATIENTRA Core MVP answers."""

    silver_path, silver_rows = _read_csv(
        silver_admissions, SILVER_ADMISSION_FIELDS, "Silver admissions"
    )
    gold_path, gold_rows = _read_csv(gold, GOLD_FIELDS, "Gold")
    identity_path, identity = _read_json(identity_audit, "identity audit")
    analytics_path, analytics = _read_json(analytics_report, "analytics report")
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() and not overwrite:
        raise CoreMvpError(
            "Core MVP output already exists; use --overwrite for an intentional rerun."
        )

    admissions_by_id, admissions_by_patient = _admissions(silver_rows)
    matching = _matching_impact(gold_rows, admissions_by_id, admissions_by_patient)
    _validate_analytics_reconciliation(analytics, matching)
    diagnosis = _diagnosis_result(analytics, gold_rows)
    identity_result = _identity_result(identity)

    payload = {
        "core_mvp_rule_version": RULE_VERSION,
        "questions": {
            "matching_impact": matching,
            "highest_released_readmission_diagnosis": diagnosis,
            "identity_resolution_workload": identity_result,
        },
        "source_rule_versions": {
            "identity": identity.get("rule_version"),
            "gold": analytics.get("gold_feature_rule_version"),
            "analytics": analytics.get("analytics_rule_version"),
        },
        "source_sha256": {
            "silver_admissions": _sha256(silver_path),
            "gold": _sha256(gold_path),
            "identity_audit": _sha256(identity_path),
            "analytics_report": _sha256(analytics_path),
        },
        "interpretation_boundary": (
            "Aggregate synthetic-case-study evidence only; no causal, clinical, "
            "patient-level risk, or production matching conclusion."
        ),
    }
    _write_json(output_path, payload)

    before_value = matching["before_identity_matching"]
    after_value = matching["after_identity_matching"]
    if not isinstance(before_value, dict) or not isinstance(after_value, dict):
        raise CoreMvpError("Matching-impact result is malformed.")
    before = cast(dict[str, object], before_value)
    after = cast(dict[str, object], after_value)
    return CoreMvpResult(
        rule_version=RULE_VERSION,
        eligible_admissions=int(matching["eligible_admissions"]),
        before_matching_rate_pct=float(before["readmission_rate_pct"]),
        after_matching_rate_pct=float(after["readmission_rate_pct"]),
        hidden_readmissions=int(matching["hidden_cross_hospital_readmissions"]),
        highest_diagnosis_group=str(diagnosis["diagnosis_group"]),
        highest_diagnosis_rate_pct=float(diagnosis["readmission_rate_pct"]),
        automatic_matches=int(identity_result["automatic_matches"]),
        review_candidates=int(identity_result["sent_for_human_review"]),
        output_path=str(output_path),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate the three aggregate PATIENTRA Core MVP answers."
    )
    parser.add_argument("--silver-admissions", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--identity-audit", required=True)
    parser.add_argument("--analytics-report", required=True)
    parser.add_argument("--output", default="outputs/mvp/patientra_core_mvp.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = build_core_mvp(
            args.silver_admissions,
            args.gold,
            args.identity_audit,
            args.analytics_report,
            args.output,
            overwrite=args.overwrite,
        )
    except CoreMvpError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "after_matching_rate_pct": result.after_matching_rate_pct,
                "automatic_matches": result.automatic_matches,
                "before_matching_rate_pct": result.before_matching_rate_pct,
                "hidden_readmissions": result.hidden_readmissions,
                "highest_diagnosis_group": result.highest_diagnosis_group,
                "highest_diagnosis_rate_pct": result.highest_diagnosis_rate_pct,
                "output_path": result.output_path,
                "review_candidates": result.review_candidates,
                "rule_version": result.rule_version,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0
