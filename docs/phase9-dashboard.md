# Phase 9 — Controlled aggregate dashboard

## Scope

The responsive dashboard at `/` and `/dashboard` is served by the existing FastAPI
application. It consumes the Phase 8 bearer-authenticated aggregate endpoints on
the same origin. The public HTML/CSS/JavaScript shell contains no release values
or embedded credentials. Approved data appears only after a successful connection.

The view includes overall readmission metrics and Wilson intervals, eligible and
excluded admissions, unique master patients when assessed, release validation,
current/publication freshness, technical quality, suppression counts, artifact
hashes, and unsuppressed breakdowns. A dimension selector filters the released
rows already fetched; it never requests category or intersecting filters.

## Use

Open `/dashboard`, enter the existing API bearer token without a `Bearer` prefix,
and select **Connect**. Use **Refresh** to retrieve a new complete view. Select
**Disconnect** to remove credentials and displayed results. Swagger remains at
`/docs`. The dashboard works with both the local SQLite API mode and hosted bundle
mode; the local CLI remains bound to loopback.

Tokens remain in JavaScript memory and are sent only in the Authorization header.
There is no browser storage, cookie, token-in-URL, external chart library, analytics,
export action, or third-party dashboard resource. Rendering uses text nodes, not
HTML assembled from API values. A self-only content security policy prohibits
framing, inline scripts, and external connections. Responses are `no-store` with
`nosniff`, `no-referrer`, and `DENY` framing headers.

## Failure and consistency controls

Each load clears the previous display and retrieves all aggregate pages with
bounded page size. Counts are reconciled, and pipeline hashes and release times
are rechecked after loading to reject a release changed during the request.
Authentication failures clear credentials; missing release, inconsistent response,
timeout, connectivity failure, and rate limits clear displayed results. Rate limits
ask the operator to wait before retrying. The hosted process permits 60 authenticated
requests/minute; a normal current-release load uses five API calls. No automatic
polling is performed. A reload or page exit clears the session.

## Governance

The reconstructed release has 548 observed readmissions (19.38%), not the historical
549 (19.42%). Eight identity reviews remain unresolved. A locally validated worksheet
contains eight demonstration `ABSTAIN` decisions; validation does not apply them,
resolve those identities, or change the deployed release. The dashboard presents
only the governance counts in the approved API bundle, never the worksheet.

`PASS` reports implemented technical checks. `FRESH` and `STALE` measure analytics
run age, not source hospital-record freshness. This is a synthetic-case-study
demonstration, not clinical decision support or a production clinical service.
Free Render hosting may sleep and delay responses. Per-user authorization,
distributed quotas, clinical validation, and production availability remain outside
this phase's demonstrated scope. API access and disclosure controls are preserved.

## Verification

Run `python -m pytest -q`. Dashboard tests verify static asset delivery, security
headers, no data-access expansion, unchanged bearer protection/OpenAPI paths, and
shell availability without an approved snapshot. Package assets are included in
the wheel through explicit package-data entries. Execution evidence is recorded
separately in [Phase 9 evidence](evidence/phase-9-dashboard/README.md).
