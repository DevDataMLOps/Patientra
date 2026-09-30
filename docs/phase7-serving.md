# Phase 7 — Data Serving and Observability

## Scope

PATIENTRA Phase 7 adds a local, aggregate-only SQLite publishing boundary between the independently validated Phase 6 analytics release and future dashboard/FastAPI consumers. It does **not** load or serve Gold admission rows, local patient IDs, names, labs, identity crosswalks, or human review records. Published information remains synthetic-case-study evidence, not clinical decision support.

## Required inputs

Run Phase 5 analytics and Phase 6 release validation first. The publisher requires:
- `readmission_analytics.json`
- `readmission_breakdowns.csv`
- `readmission_analytics_audit.json`
- `release_validation.json`

Before publication, it verifies the 13 passing release checks, file hashes from both audits, expected analytics rule version, approved breakdown dimensions, count reconciliation, suppression integrity, and CSV/JSON agreement. Publication fails closed if required evidence is absent or altered. A new SQLite file is written to a temporary path before atomic replacement. Explicit `--overwrite` is required when replacing a previous snapshot.

## Usage

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
patientra-serve --database outputs/phase7/patientra_serving.sqlite
```

To inspect locally:

```python
import sqlite3
with sqlite3.connect("outputs/phase7/patientra_serving.sqlite") as connection:
    print(connection.execute("SELECT * FROM overall").fetchall())
    print(connection.execute("SELECT * FROM released_breakdowns LIMIT 5").fetchall())
    print(connection.execute("SELECT * FROM pipeline_status").fetchall())
```

## Data contract

| SQLite object | Content | Access |
|---|---|---|
| `overall` | One released cohort aggregate | Approved aggregate consumers |
| `released_breakdowns` | Un-suppressed released breakdowns | Approved aggregate consumers |
| `breakdowns` | Same metrics plus suppression markers and NULL suppressed cells | Internal review only |
| `pipeline_status` | Release PASS, publication time, analytics run time, row reconciliation, rule checks, source artifact hashes | Operational consumers |

The freshness label compares the timestamp from the Phase 5 audit against publication time (24-hour threshold). It is **not** an upstream ingestion freshness SLA or proof that hospital data is current. There are no scheduling, retries, live monitoring, alerting, role-based database permissions, data retention policies or cloud hosting in this phase. Future API code must restrict query surfaces, authenticate where required, and independently assess disclosure risks from combined filters. Do not expose arbitrary SQL to an untrusted caller.

`outputs/phase7/` is Git-ignored and should stay outside published GitHub artifacts. The database is designed for read-only local development, not a multi-tenant healthcare workload. Even aggregates can reveal sensitive information when combined with auxiliary data, so public release requires independent review.

## Acceptance checklist

- [ ] Tests pass in the GitHub Actions matrix for Python 3.11/3.12 on Windows and Linux.
- [ ] With actual approved local input files, Phase 7 creates the SQLite snapshot.
- [ ] Hash tampering, absent validation and unsuppressed small cells stop publication.
- [ ] Existing snapshot remains unchanged after rejected overwrite.
- [ ] Data steward approves the serving surface before any public dashboard or API exposure.

This document describes what the implementation enforces and the remaining deployment gates; it does not claim a Phase 7 patient-data run was executed on GitHub.
