"""Phase 7 privacy, tampering and atomic publication tests."""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from patientra.serving.store import FIELDS, ServingError, publish


def _save_json(path, item):
    path.write_text(json.dumps(item), encoding="utf-8")


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release(tmp_path):
    report, breakdowns, audit, gate, db = [
        tmp_path / name for name in ("report.json", "breakdowns.csv", "audit.json",
                                    "gate.json", "served.sqlite")]
    row = {
        "dimension": "hospital", "category": "Lakeside General",
        "eligible_admissions": 40, "readmitted_admissions": 20,
        "not_readmitted_admissions": 20, "readmission_rate_pct": 50.0,
        "wilson_95_lower_pct": 35.0, "wilson_95_upper_pct": 65.0,
        "suppression_reason": "",
    }
    hidden = dict(row, category="Riverside Specialist", suppression_reason="primary_small_cell")
    hidden.update({k: None for k in FIELDS[2:-1]})
    dimensions = ("hospital", "sex", "age_band", "diagnosis_group", "discharge_status",
                  "prior_completed_admission_band", "length_of_stay_band",
                  "discharge_year", "discharge_month")
    collection = {key: [row, hidden] if key == "hospital" else [] for key in dimensions}
    _save_json(report, {
        "analytics_rule_version": "phase5-analytics-v1",
        "overall": {k: row[k] for k in FIELDS[2:-1]},
        "cohort": {"gold_admissions": 45, "eligible_admissions": 40, "excluded_admissions": 5},
        "breakdowns": collection,
        "minimum_cell_size": 11,
    })
    with breakdowns.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows([row, hidden])
    _save_json(audit, {
        "rule_version": "phase5-analytics-v1",
        "created_at_utc": "2026-09-30T12:00:00Z",
        "output_sha256": {
            "readmission_analytics.json": _hash(report),
            "readmission_breakdowns.csv": _hash(breakdowns),
        },
    })
    _save_json(gate, {
        "status": "PASS", "validation_rule_version": "phase6-validation-v1",
        "checks": [{"status": "PASS"} for _ in range(13)],
        "verified_sha256": {
            "analytics_report": _hash(report),
            "analytics_breakdowns": _hash(breakdowns),
        },
        "reconciliation": {
            "gold_rows": 45, "eligible_rows": 40, "excluded_rows": 5,
            "analytics_breakdown_rows": 2, "suppressed_breakdown_rows": 1,
        },
    })
    return report, breakdowns, audit, gate, db


def test_publication_is_aggregate_only(tmp_path):
    args = _release(tmp_path)
    outcome = publish(*args, now=datetime(2026, 9, 30, 18, tzinfo=timezone.utc))
    assert outcome["release_status"] == "PASS"
    with sqlite3.connect(args[-1]) as con:
        assert con.execute("SELECT count(*) FROM breakdowns").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM released_breakdowns").fetchone()[0] == 1
        assert con.execute("SELECT readmitted_admissions FROM breakdowns WHERE suppression_reason != ''").fetchone()[0] is None
        assert con.execute("SELECT freshness_status FROM pipeline_status").fetchone()[0] == "FRESH"
        assert set(row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")) == {"overall", "breakdowns", "pipeline_status"}


def test_rejects_tampered_release_without_replacing_database(tmp_path):
    args = _release(tmp_path)
    publish(*args)
    original = args[-1].read_bytes()
    args[0].write_text(args[0].read_text() + " ", encoding="utf-8")
    with pytest.raises(ServingError, match="hashes"):
        publish(*args, overwrite=True)
    assert args[-1].read_bytes() == original


def test_rejects_leaked_suppressed_metric(tmp_path):
    args = _release(tmp_path)
    content = json.loads(args[0].read_text())
    content["breakdowns"]["hospital"][1]["readmitted_admissions"] = 1
    _save_json(args[0], content)
    audit = json.loads(args[2].read_text())
    audit["output_sha256"]["readmission_analytics.json"] = _hash(args[0])
    _save_json(args[2], audit)
    gate = json.loads(args[3].read_text())
    gate["verified_sha256"]["analytics_report"] = _hash(args[0])
    _save_json(args[3], gate)
    with pytest.raises(ServingError, match="Suppressed"):
        publish(*args)
    assert not args[-1].exists()


def test_existing_database_requires_explicit_overwrite(tmp_path):
    args = _release(tmp_path)
    publish(*args)
    with pytest.raises(ServingError, match="overwrite"):
        publish(*args)


def test_missing_release_is_fail_closed(tmp_path):
    args = _release(tmp_path)
    args[3].unlink()
    with pytest.raises(ServingError):
        publish(*args)
    assert not args[-1].exists()
