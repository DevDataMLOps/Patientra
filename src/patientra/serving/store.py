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
            or len({c.get("check") for c in checks if isinstance(c, dict)}) != 13
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


def publish(report_path, csv_path, audit_path, gate_path, database, *, overwrite=False, now=None):
    """Atomically replace the aggregate-only serving snapshot after validation."""
    source = [Path(p).expanduser().resolve() for p in
              (report_path, csv_path, audit_path, gate_path)]
    target = Path(os.path.abspath(Path(database).expanduser()))
    if target.is_symlink() or (target.exists() and not overwrite):
        raise ServingError("Refusing existing or symlink database without explicit overwrite")
    report, rows, audit = verify(*source)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ServingError("Publication time must be timezone-aware")
    try:
        run_at = datetime.fromisoformat(audit["created_at_utc"].replace("Z", "+00:00"))
        if run_at.utcoffset() is None:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ServingError("Missing timestamp in Phase 5 audit") from exc
    age = max(0, int((moment - run_at).total_seconds()))
    freshness = "STALE" if age > 86400 else "FRESH"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".patientra-",
                                     suffix=".sqlite", delete=False) as f:
        tmp = Path(f.name)
    try:
        with sqlite3.connect(tmp) as conn:
            conn.executescript("""
                CREATE TABLE overall (
                    eligible_admissions INTEGER, readmitted_admissions INTEGER,
                    not_readmitted_admissions INTEGER, readmission_rate_pct REAL,
                    wilson_95_lower_pct REAL, wilson_95_upper_pct REAL
                );
                CREATE TABLE breakdowns (
                    dimension TEXT, category TEXT, eligible_admissions INTEGER,
                    readmitted_admissions INTEGER, not_readmitted_admissions INTEGER,
                    readmission_rate_pct REAL, wilson_95_lower_pct REAL,
                    wilson_95_upper_pct REAL, suppression_reason TEXT,
                    PRIMARY KEY (dimension, category)
                );
                CREATE TABLE pipeline_status (
                    release_status TEXT, freshness_status TEXT,
                    published_at_utc TEXT, source_run_at_utc TEXT,
                    source_age_seconds INTEGER, gold_rows INTEGER,
                    eligible_rows INTEGER, excluded_rows INTEGER,
                    breakdown_rows INTEGER, suppressed_rows INTEGER,
                    validation_checks_passed INTEGER, minimum_cell_size INTEGER,
                    analytics_sha256 TEXT, breakdown_sha256 TEXT,
                    gate_sha256 TEXT
                );
                CREATE VIEW released_breakdowns AS
                  SELECT * FROM breakdowns WHERE suppression_reason = '';
            """)
            conn.execute("INSERT INTO overall VALUES (?,?,?,?,?,?)",
                         tuple(report["overall"][k] for k in METRICS))
            conn.executemany("INSERT INTO breakdowns VALUES (?,?,?,?,?,?,?,?,?)",
                             [tuple(row[k] for k in FIELDS) for row in rows])
            cohort = report["cohort"]
            conn.execute("INSERT INTO pipeline_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("PASS", freshness, moment.isoformat(), run_at.isoformat(),
                          age, cohort["gold_admissions"], cohort["eligible_admissions"],
                          cohort["excluded_admissions"], len(rows),
                          sum(bool(row["suppression_reason"]) for row in rows),
                          13, report["minimum_cell_size"], sha(source[0]),
                          sha(source[1]), sha(source[3])))
            conn.commit()
        conn.close()
        os.replace(tmp, target)
    except (OSError, sqlite3.Error, KeyError) as exc:
        raise ServingError("Atomic aggregate publication failed") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return {"release_status": "PASS", "freshness_status": freshness,
            "breakdown_rows": len(rows), "database": str(target)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="PATIENTRA Phase 7 validated aggregate serving")
    parser.add_argument("--report", default="outputs/phase5/readmission_analytics.json")
    parser.add_argument("--breakdowns", default="outputs/phase5/readmission_breakdowns.csv")
    parser.add_argument("--audit", default="outputs/phase5/readmission_analytics_audit.json")
    parser.add_argument("--validation", default="outputs/phase6/release_validation.json")
    parser.add_argument("--database", default="outputs/phase7/patientra_serving.sqlite")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = publish(args.report, args.breakdowns, args.audit,
                          args.validation, args.database, overwrite=args.overwrite)
    except ServingError as exc:
        parser.error(str(exc))
    print(json.dumps(outcome, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
