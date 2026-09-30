"""Phase 6 end-to-end release validation for PATIENTRA."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from patientra.analytics.readmission import BREAKDOWN_FIELDS
from patientra.features.gold import GOLD_FIELDS


RULE_VERSION = "phase6-validation-v1"
EXPECTED_PACKAGE_VERSION = "0.6.1"
EVIDENCE_FILES = (
    "docs/evidence/phase-1-bronze/README.md",
    "docs/evidence/phase-2-silver/README.md",
    "docs/evidence/phase-3-identity-resolution/README.md",
    "docs/evidence/phase-4-gold-features/README.md",
    "docs/evidence/phase-5-readmission-analytics/README.md",
)


class ValidationError(RuntimeError):
    """Raised when a Phase 6 release check fails."""


@dataclass(frozen=True)
class ValidationResult:
    rule_version: str
    status: str
    checks_passed: int
    gold_rows: int
    eligible_rows: int
    excluded_rows: int
    analytics_breakdown_rows: int
    suppressed_breakdown_rows: int
    output_path: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise ValidationError(f"Missing required {label} file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"The {label} file is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"The {label} file must contain a JSON object.")
    return value


def _read_csv(path: Path, fields: tuple[str, ...], label: str) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValidationError(f"Missing required {label} file.")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(fields):
                raise ValidationError(f"The {label} schema does not match its contract.")
            return list(reader)
    except ValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError(f"The {label} file could not be read safely.") from exc


def _json_breakdown_rows(report: dict[str, object]) -> list[dict[str, object]]:
    breakdowns = report.get("breakdowns")
    if not isinstance(breakdowns, dict):
        raise ValidationError("Analytics report breakdowns are missing.")
    rows: list[dict[str, object]] = []
    for values in breakdowns.values():
        if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
            raise ValidationError("Analytics report breakdowns are malformed.")
        rows.extend(values)
    return rows


def _normalized_breakdown(row: dict[str, object]) -> tuple[str, ...]:
    return tuple("" if row.get(field) is None else str(row.get(field, "")) for field in BREAKDOWN_FIELDS)


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
        raise ValidationError("The validation report could not be written atomically.") from exc


def validate_release(
    repository_root: str | Path,
    gold: str | Path,
    gold_audit: str | Path,
    analytics_report: str | Path,
    analytics_breakdowns: str | Path,
    analytics_audit: str | Path,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> ValidationResult:
    """Validate Phase 1–5 evidence and Phase 4–5 output reconciliation."""

    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise ValidationError("repository_root must be an existing directory.")
    paths = {
        "gold": Path(gold).expanduser().resolve(),
        "gold_audit": Path(gold_audit).expanduser().resolve(),
        "analytics_report": Path(analytics_report).expanduser().resolve(),
        "analytics_breakdowns": Path(analytics_breakdowns).expanduser().resolve(),
        "analytics_audit": Path(analytics_audit).expanduser().resolve(),
    }
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise ValidationError(
            "Validation output already exists; use --overwrite for an intentional rerun."
        )

    checks: list[dict[str, str]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        if not condition:
            raise ValidationError(f"Validation check failed: {name}.")
        checks.append({"check": name, "status": "PASS", "detail": detail})

    evidence_exists = all((root / relative).is_file() for relative in EVIDENCE_FILES)
    check("phase_evidence_files", evidence_exists, "Phase 1–5 evidence files exist.")
    index_path = root / "docs/evidence/README.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    check(
        "phase_evidence_index",
        all(f"phase-{phase}" in index_text.lower() for phase in range(1, 6))
        and index_text.count("Complete") >= 5,
        "Evidence index marks Phases 1–5 complete.",
    )
    pyproject_path = root / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError) as exc:
        raise ValidationError("pyproject.toml could not be validated.") from exc
    check(
        "package_version",
        project.get("version") == EXPECTED_PACKAGE_VERSION,
        f"Package version is {EXPECTED_PACKAGE_VERSION}.",
    )
    gitignore_path = root / ".gitignore"
    gitignore = gitignore_path.read_text(encoding="utf-8") if gitignore_path.is_file() else ""
    check(
        "sensitive_output_ignore_rules",
        "data/gold/**" in gitignore and "outputs/**" in gitignore,
        "Gold and analytics output trees are Git-ignored.",
    )

    gold_rows = _read_csv(paths["gold"], GOLD_FIELDS, "Gold")
    gold_audit_data = _read_json(paths["gold_audit"], "Gold audit")
    report = _read_json(paths["analytics_report"], "analytics report")
    analytics_audit_data = _read_json(paths["analytics_audit"], "analytics audit")
    breakdown_csv = _read_csv(
        paths["analytics_breakdowns"], BREAKDOWN_FIELDS, "analytics breakdown"
    )
    gold_hash = _sha256(paths["gold"])
    check(
        "gold_hash_lineage",
        analytics_audit_data.get("gold_input_sha256") == gold_hash,
        "Analytics audit Gold hash matches the validated Gold file.",
    )
    output_hashes = analytics_audit_data.get("output_sha256")
    check(
        "analytics_output_hashes",
        isinstance(output_hashes, dict)
        and output_hashes.get("readmission_analytics.json")
        == _sha256(paths["analytics_report"])
        and output_hashes.get("readmission_breakdowns.csv")
        == _sha256(paths["analytics_breakdowns"]),
        "Analytics report and breakdown hashes match the audit.",
    )

    admission_ids = [row["admission_id"] for row in gold_rows]
    check(
        "gold_row_uniqueness",
        len(admission_ids) == len(set(admission_ids))
        and len(gold_rows) == gold_audit_data.get("gold_rows"),
        "Gold rows reconcile and admission IDs are unique.",
    )
    labels = Counter(
        {"1": "positive", "0": "negative", "": "unlabeled"}[row["readmitted_30d"]]
        for row in gold_rows
    )
    statuses = Counter(row["label_status"] for row in gold_rows)
    check(
        "gold_label_audit_reconciliation",
        dict(sorted(labels.items())) == gold_audit_data.get("label_counts")
        and dict(sorted(statuses.items())) == gold_audit_data.get("label_status_counts"),
        "Gold labels and statuses match the Phase 4 audit.",
    )
    cohort = report.get("cohort")
    overall = report.get("overall")
    if not isinstance(cohort, dict) or not isinstance(overall, dict):
        raise ValidationError("Analytics report cohort or overall metrics are missing.")
    check(
        "gold_analytics_reconciliation",
        cohort.get("gold_admissions") == len(gold_rows)
        and cohort.get("eligible_admissions") == labels["positive"] + labels["negative"]
        and cohort.get("excluded_admissions") == labels["unlabeled"]
        and overall.get("readmitted_admissions") == labels["positive"]
        and overall.get("not_readmitted_admissions") == labels["negative"],
        "Analytics cohort and outcomes reconcile to Gold labels.",
    )

    json_breakdowns = _json_breakdown_rows(report)
    check(
        "breakdown_csv_json_reconciliation",
        Counter(_normalized_breakdown(row) for row in json_breakdowns)
        == Counter(_normalized_breakdown(row) for row in breakdown_csv),
        "JSON and CSV breakdown rows match exactly.",
    )
    metric_fields = (
        "eligible_admissions",
        "readmitted_admissions",
        "not_readmitted_admissions",
        "readmission_rate_pct",
        "wilson_95_lower_pct",
        "wilson_95_upper_pct",
    )
    suppressed = [row for row in json_breakdowns if row.get("suppression_reason")]
    check(
        "suppression_integrity",
        all(all(row.get(field) is None for field in metric_fields) for row in suppressed)
        and len(suppressed) == analytics_audit_data.get("suppressed_breakdown_rows"),
        "Suppressed rows contain no metrics and match the audit count.",
    )
    analytics_text = "".join(
        path.read_text(encoding="utf-8")
        for key, path in paths.items()
        if key.startswith("analytics_")
    )
    identifiers = set(admission_ids) | {
        row["master_patient_id"] for row in gold_rows
    }
    check(
        "identifier_exclusion",
        not any(identifier and identifier in analytics_text for identifier in identifiers),
        "No actual Gold admission or master identifier occurs in analytics outputs.",
    )
    check(
        "rule_version_chain",
        gold_audit_data.get("rule_version") == "phase4-gold-v1"
        and report.get("gold_feature_rule_version") == "phase4-gold-v1"
        and report.get("analytics_rule_version") == "phase5-analytics-v1"
        and analytics_audit_data.get("rule_version") == "phase5-analytics-v1",
        "Phase 4 and Phase 5 rule versions are consistent.",
    )

    result = ValidationResult(
        rule_version=RULE_VERSION,
        status="PASS",
        checks_passed=len(checks),
        gold_rows=len(gold_rows),
        eligible_rows=int(cohort["eligible_admissions"]),
        excluded_rows=int(cohort["excluded_admissions"]),
        analytics_breakdown_rows=len(json_breakdowns),
        suppressed_breakdown_rows=len(suppressed),
        output_path=str(output_path),
    )
    payload = {
        "validation_rule_version": RULE_VERSION,
        "status": "PASS",
        "checks": checks,
        "reconciliation": {
            "gold_rows": result.gold_rows,
            "eligible_rows": result.eligible_rows,
            "excluded_rows": result.excluded_rows,
            "analytics_breakdown_rows": result.analytics_breakdown_rows,
            "suppressed_breakdown_rows": result.suppressed_breakdown_rows,
        },
        "verified_sha256": {
            "gold": gold_hash,
            "analytics_report": _sha256(paths["analytics_report"]),
            "analytics_breakdowns": _sha256(paths["analytics_breakdowns"]),
        },
        "scope_boundary": (
            "Validation covers repository evidence, output integrity, reconciliation, "
            "suppression, and identifier exclusion; it does not validate clinical use."
        ),
    }
    _write_json(output_path, payload)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PATIENTRA Phase 6 release validation.")
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--gold", type=Path, default=Path("data/gold/readmission_features.csv"))
    parser.add_argument(
        "--gold-audit", type=Path, default=Path("data/gold/readmission_feature_audit.json")
    )
    parser.add_argument(
        "--analytics-report",
        type=Path,
        default=Path("outputs/phase5/readmission_analytics.json"),
    )
    parser.add_argument(
        "--analytics-breakdowns",
        type=Path,
        default=Path("outputs/phase5/readmission_breakdowns.csv"),
    )
    parser.add_argument(
        "--analytics-audit",
        type=Path,
        default=Path("outputs/phase5/readmission_analytics_audit.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/phase6/release_validation.json")
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_release(
            args.repository_root,
            args.gold,
            args.gold_audit,
            args.analytics_report,
            args.analytics_breakdowns,
            args.analytics_audit,
            args.output,
            overwrite=args.overwrite,
        )
    except ValidationError as exc:
        parser.error(str(exc))
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
