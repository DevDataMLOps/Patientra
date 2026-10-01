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
safe shell behavior when the snapshot is unavailable. A built wheel was inspected
and contains the three dashboard assets, without data/tests/outputs folders.

Render reports source revision `51fd40f377a6a821b3d9ac4ef16f67bfc09d0ac0`
as **Live**, deployment `dep-dav8bc6k1f9s73d7f040`. All four CI jobs
(Windows/Linux, Python 3.11/3.12) passed for that code revision.
The native build preserves the Phase 8 private aggregate mount and removes
public source synthetic starter/test folders and Git history from the runtime.

The [public verification record](public-verification.json) records the actual
HTTPS verification time, deployed code, response codes, and browser observations.

| Verified behavior | Observed result |
|---|---|
| `/`, `/dashboard`, CSS, JavaScript, Swagger and OpenAPI | HTTP 200 |
| Overall and quality API without authentication | HTTP 401 |
| Dashboard headers | no-store, nosniff, no-referrer, DENY, self-only CSP |
| Authenticated headline rate / readmissions / eligible | 19.38% / 548 / 2,827 |
| Unique master patients / unresolved identity reviews | 2,000 / 8 |
| All nine dimension selections | 43 released rows; counts match local approved bundle |
| Invalid bearer token | Rejected; no data retained |
| Refresh and reload | Refresh reloads approved data; reload resets connection |
| Disconnect | Token field, aggregate text and table rows cleared |
| Mobile breakpoint | 390 px viewport; no document horizontal overflow |

The approved local bundle was independently compared to browser headline values
and all nine dimension row counts. No matching secrets, case identifiers,
patient-level values, reviewer provenance, database, or token is committed.
The demonstration worksheet remains local and unapplied; the dashboard cannot
complete or adjudicate reviews. Production load/availability, per-user access
controls, clinical validation, and broader device/browser coverage are unverified.
