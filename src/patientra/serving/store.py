"""Publish validated, privacy-suppressed Phase 5 aggregates to a local SQLite store."""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

METRICS = ("eligible_admissions", "readmitted_admissions", "not_readmitted_admissions",
           "readmission_rate_pct", "wilson_95_lower_pct", "wilson_95_upper_pct")
DIMENSIONS = {"hospital", "sex", "age_band", "diagnosis_group", "discharge_status",
              "prior_completed_admission_band", "length_of_stay_band", "discharge_year",
              "discharge_month"}
FIELDS = ("dimension", "category", *METRICS, "suppression_reason")


class ServingError(RuntimeError):
    """Release evidence did not satisfy the serving contract."""


def sha(path):
    path = Path(path)
    if not path.is_file():
        raise ServingError("Missing release input")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServingError("Unreadable release JSON") from exc
    if not isinstance(value, dict):
        raise ServingError("Release JSON must be an object")
    return value


def verify(report_path, csv_path, audit_path, gate_path):
    gate, audit, report = read_json(gate_path), read_json(audit_path), read_json(report_path)
    checks = gate.get("checks")
    if (gate.get("status") != "PASS"
            or gate.get("validation_rule_version") != "phase6-validation-v1"
            or not isinstance(checks, list) or len(checks) != 13
            or any(not isinstance(c, dict) or c.get("status") != "PASS" for c in checks)):
        raise ServingError("Phase 6 release gate has not passed")
    hashes = gate.get("verified_sha256", {})
    if not isinstance(hashes, dict) or hashes.get("analytics_report") != sha(report_path) or hashes.get("analytics_breakdowns") != sha(csv_path):
        raise ServingError("Phase 6 hashes do not match inputs")
    audit_hashes = audit.get("output_sha256", {})
    if (audit.get("rule_version") != "phase5-analytics-v1"
            or not isinstance(audit_hashes, dict)
            or audit_hashes.get("readmission_analytics.json") != sha(report_path)
            or audit_hashes.get("readmission_breakdowns.csv") != sha(csv_path)):
        raise ServingError("Phase 5 audit hashes do not match inputs")
    if report.get("analytics_rule_version") != "phase5-analytics-v1":
        raise ServingError("Wrong analytics rule version")
    overall = report.get("overall", {})
    breakdowns = report.get("breakdowns", {})
    cohort = report.get("cohort", {})
    if not isinstance(overall, dict) or set(overall) != set(METRICS) or not isinstance(breakdowns, dict) or set(breakdowns) != DIMENSIONS or not isinstance(cohort, dict):
        raise ServingError("Analytics schema mismatch")
    for key in METRICS[:3]:
        if type(overall[key]) is not int or overall[key] < 0:
            raise ServingError("Invalid overall count")
    if overall[METRICS[0]] != overall[METRICS[1]] + overall[METRICS[2]]:
        raise ServingError("Overall counts mismatch")
    expected = []
    for dimension, rows in breakdowns.items():
        if not isinstance(rows, list):
            raise ServingError("Invalid breakdown rows")
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(FIELDS) or row["dimension"] != dimension:
                raise ServingError("Unapproved breakdown schema")
            if not isinstance(row["category"], str) or not row["category"] or len(row["category"]) > 128:
                raise ServingError("Invalid aggregate category")
            reason = row["suppression_reason"]
            if reason not in ("", "primary_small_cell", "complementary_suppression"):
                raise ServingError("Invalid suppression reason")
            if reason and any(row[k] is not None for k in METRICS):
                raise ServingError("Suppressed metric is not null")
            if not reason and (any(type(row[k]) not in (float, int) for k in METRICS)
                               or row[METRICS[0]] != row[METRICS[1]] + row[METRICS[2]]):
                raise ServingError("Invalid breakdown metric")
            expected.append(row)
    try:
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(FIELDS):
                raise ServingError("Breakdown CSV schema mismatch")
            actual = list(reader)
    except (OSError, csv.Error) as exc:
        raise ServingError("Unreadable breakdown CSV") from exc
    normalize = lambda row: tuple("" if row[k] is None else str(row[k]) for k in FIELDS)
    if sorted(map(normalize, expected)) != sorted(map(normalize, actual)):
        raise ServingError("CSV/JSON breakdown mismatch")
    reconciliation = gate.get("reconciliation", {})
    if not isinstance(reconciliation, dict) or any(reconciliation.get(key) != cohort.get(field) for key, field in (("gold_rows", "gold_admissions"), ("eligible_rows", "eligible_admissions"), ("excluded_rows", "excluded_admissions"))):
        raise ServingError("Gate/cohort mismatch")
    if reconciliation.get("analytics_breakdown_rows") != len(expected) or reconciliation.get("suppressed_breakdown_rows") != sum(bool(r["suppression_reason"]) for r in expected):
        raise ServingError("Gate/breakdown mismatch")
    return report, expected, audit
