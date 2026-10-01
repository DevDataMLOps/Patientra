# Phase 9 evidence — Controlled aggregate dashboard

## Objective and acceptance boundary

Provide a responsive browser dashboard for approved overall metrics, released
breakdowns, pipeline observability, and technical data quality. Keep the existing
bearer authentication, suppression boundary, and identity-governance limitations.
The dashboard reads only the Phase 8 API; no patient-level inputs or review packets
are served or included in these evidence files.

## Architecture

Bronze → Silver → Identity Resolution → Gold → Analytics → Phase 6 Validation →
Phase 7 SQLite → Phase 8 approved aggregate API → Phase 9 dashboard.

Hosted mode privately mounts the approved aggregate-only export and keeps SQLite
local. The static dashboard shell is public; data endpoints remain authenticated.
See the [dashboard contract](../../phase9-dashboard.md) and the prior
[Phase 8 public verification](../phase-8-fastapi/public-http-verification.json).

## Governance limitations

**Eight patient identity-review cases remain unresolved.** The local demo worksheet
validates with eight `ABSTAIN` decisions; those decisions have not been applied.
The dashboard cannot certify identities. Reconstructed 548 readmissions and 19.38%
are distinct from the historical human-reviewed 549 and 19.42% release.

Technical `PASS` does not establish clinical accuracy or complete identity resolution.
Freshness refers to analytics-run recency, not underlying hospital records. This
is an aggregate demonstration rather than a production clinical service.

## Execution record

The complete local suite passed **105 tests**, with one upstream Starlette/HTTPX
deprecation warning. JavaScript syntax validation passed using `node --check`.
Dashboard delivery/security tests preserve authenticated data endpoints and check
safe shell behavior when the snapshot is unavailable. Public deployment and browser
execution results will be added after actual verification.
