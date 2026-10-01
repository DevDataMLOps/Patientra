# Phase 8 evidence — Controlled aggregate FastAPI endpoints

## Objective and acceptance boundary

Expose approved aggregate analytics, pipeline status, and technical data-quality
metrics through an authenticated, read-only FastAPI service while preserving
suppression and the Phase 7 release boundary. The original execution below was
local and used historical aggregates. The public deployment follow-up at the end
records the reconstructed release on Render. No production clinical service is claimed.

## Execution provenance

The local HTTP smoke test used the available **historical human-reviewed aggregate
release**, not the reconstructed run described in Phase 7 evidence. Its existing
Phase 5 JSON, breakdown CSV, analytics audit, and Phase 6 validation report passed
the Phase 7 publisher's checks and produced a local snapshot at
`outputs/phase7/patientra_serving.sqlite`. No upstream patient-level files were
read or copied for this execution.

The snapshot was then pinned by its locally calculated SHA-256 and queried through
a real Uvicorn server bound to loopback. An ephemeral random bearer token was kept
in process memory and never printed or committed. The server was stopped after
verification. The database remains Git-ignored and is not a GitHub artifact.

## Verified local outcomes

| Measure | Observed result |
|---|---:|
| Authenticated `/health` and `/ready` | HTTP 200 |
| Authenticated overall, breakdown, pipeline-status and data-quality endpoints | HTTP 200 |
| Eligible admissions | 2,827 |
| Historical 30-day readmissions | 549 |
| Historical readmission rate | 19.42% |
| Gold / eligible / excluded rows | 2,938 / 2,827 / 111 |
| Total / released / suppressed breakdown rows | 51 / 43 / 8 |
| Validation checks passed | 13 |
| Minimum released cell size | 11 |
| Release status | PASS |
| Freshness at this publication / current request | STALE / STALE |
| Missing bearer credentials | HTTP 401 |
| Unapproved dimension or excessive page limit | HTTP 422 |
| POST to the overall endpoint | HTTP 405 |
| Database bytes after HTTP verification | Unchanged |

The API returned only unsuppressed breakdowns. It independently reconciled the
snapshot's cohort and suppression counts before returning results. It returned
`identity_resolution: not_assessed` and `clinical_accuracy: not_assessed`; it
does not infer these properties from release `PASS`.

The analytics run predates this publication by more than the 24-hour freshness
threshold, so `STALE` is the expected result. The source audit timestamp was not
changed to manufacture freshness. No screenshot, execution timestamp, or artifact
checksum is invented or needed to support this summary.

## Architecture and endpoint controls

Phase 6 validation → Phase 7 aggregate SQLite snapshot → operator-approved
snapshot hash → bearer-authenticated Phase 8 FastAPI → approved aggregate clients.

- `/api/v1/overall`: approved cohort counts, rate, and confidence intervals.
- `/api/v1/breakdowns`: unsuppressed rows only; optional allowlisted dimension;
  deterministic pagination with at most 100 rows per response.
- `/api/v1/pipeline-status`: release status, source/publication metadata, artifact
  hashes, and separately labeled publication/current freshness.
- `/api/v1/data-quality`: cohort reconciliation, exclusion counts, breakdown and
  suppression counts, minimum cell size, and implemented validation checks.
- Authenticated `/health` measures process liveness; `/ready` verifies that the
  configured snapshot can be served safely. Neither is a clinical-readiness gate.

Every data request checks the exact snapshot bytes against the configured digest
before deserializing them into a private read-only in-memory connection. Missing,
changed, malformed, corrupt, or failed-release snapshots return generic 503 errors.
Fixed schemas, explicit field projections, suppression checks, and response models
restrict the serving surface. There are no arbitrary SQL, patient, write, category
filter, joined filter, or unauthenticated schema endpoints.

See [the Phase 8 contract and reproduction commands](../../phase8-api.md).

## Automated verification

- Full existing and new synthetic-fixture suite: **85 passed** locally on Python 3.11.
- `python -m compileall -q src tests`: passed.
- Dependency check (`python -m pip check`): no broken requirements.
- API installation through `requirements.txt` and the `patientra-api` entry point
  succeeded. The real HTTP smoke test executed the equivalent module entry point.
- Tests exercise every route's authentication, suppression exclusion, approved
  response fields, read-only access, tampering/missing/corrupt snapshots, malformed
  metadata and metrics, closed query surfaces, pagination, safe errors, and dynamic
  freshness. A tampered release view cannot expand the returned rows.
- One upstream Starlette test-client deprecation warning was reported for HTTPX;
  no test failed. The GitHub Actions Windows/Linux Python 3.11/3.12 matrix is not
  represented as locally executed evidence.

## Governance and remaining limits

This execution's 549 readmissions and 19.42% rate belong to the historical release.
They do not independently verify, replace, or equate to the reconstructed Phase 7
run's 548 readmissions, 19.38% rate, and 2,000 master patients.
**Eight patient identity-review cases remain unresolved in that reconstructed run.**
Its original database and audits were unavailable during the historical smoke test;
the separate reconstruction verified later is documented below.

`PASS` denotes the implemented technical release checks, not clinical accuracy or
complete identity resolution. Freshness measures analytics-run age, not hospital
record freshness. Data-quality endpoints do not measure source completeness,
quarantine rates, clinical validity, or identity-review completion.

The original local execution used one shared bearer credential and loopback HTTP.
The subsequent Render deployment adds managed HTTPS and a process-level rate
limit; it does not add per-user roles, distributed quotas, clinical validation,
or continuous operational monitoring.
No raw datasets, patient-level CSVs, crosswalks, review queues, identifiers, matching
secrets, API tokens, or SQLite database are included in the committed evidence.

## Follow-up: independently verified reconstructed run and hosted mode

A separate isolated reconstruction now verifies the operator-supplied Phase 7
figures directly. It uses protected Silver inputs, a stable local matching key
for this reconstruction, no supplied human-review decisions, and the existing
observation cutoff. Historical artifacts and decisions were preserved. The
original operator-run database remains a separate artifact; matching aggregate
figures do not establish identical identifiers, timestamps, or hashes.

| Reconstructed measure | Verified result |
|---|---:|
| Automatic matches / pending identity reviews | 304 / 8 |
| Unique master patients | 2,000 |
| Gold / eligible / excluded rows | 2,938 / 2,827 / 111 |
| Observed 30-day readmissions / provisional rate | 548 / 19.38% |
| Breakdown / released / suppressed rows | 51 / 43 / 8 |
| Phase 6 release checks | 13 passed |
| Phase 7 publication / freshness | PASS / FRESH |
| Hosted-mode authenticated HTTP endpoints | All six returned 200 locally |
| Missing auth / invalid query / POST / untrusted host | 401 / 422 / 405 / 400 |
| Extended automated suite | 103 passed locally |

The hosted HTTP test read only a typed, hash-pinned JSON release bundle. Suppressed
categories, protected metrics, patient rows, and the database were not in that
bundle. Local export checked identity-to-Gold and release lineage before including
`reviews_unresolved`, eight unresolved reviews, and 2,000 master patients in the
quality response. This **does not resolve the reviews** or make the reconstruction
identical to the historical 549-readmission release.

Compilation and dependency checks passed; upload inventory checks found no
unexpected files. The Google Cloud deployment preflight detected disabled billing and stopped
before changing resources. At that stage, public deployment was pending. The
subsequent Render deployment is recorded below; no Cloud Run image build or
container execution is claimed. See the [deployment contract](../../phase8-cloud-deployment.md).

## Public deployment follow-up: Render

After the Google Cloud billing preflight, the user selected another provider.
Render built and installed the Python package successfully and reports the native
Python web service as live at https://patientra-api.onrender.com. The deployed
revision is `c019980533f3f6f7b026b214cc915ad36e0f4963`.

The first startup rejected an invalid token configuration. A provider-generated
secret corrected that configuration; the subsequent environment deployment is
live. Public HTTPS `/health` returned 401 with `Authentication required` without
credentials. Authenticated readiness and all aggregate endpoints returned 200
and matched the approved local release. Invalid queries returned 422, POST returned
405, and schema/documentation routes returned 404.

The Render hostname test raises the complete local suite to **104 passed**, with
one upstream Starlette/HTTPX deprecation warning. All four GitHub Actions jobs
(Windows/Linux, Python 3.11/3.12) passed for the deployed revision.

Only the typed, unsuppressed aggregate bundle is privately mounted by Render;
patient-level files, matching secrets, identity reviews, and SQLite remain local.
**Eight identity-review cases remain unresolved.** The reconstruction remains
548 readmissions (19.38%), distinct from historical 549 (19.42%). `PASS` is a
technical release check; `FRESH` measures analytics recency. Neither establishes
clinical accuracy. The free instance sleeps when idle and is not a production
clinical service. See the [deployment contract](../../phase8-cloud-deployment.md).

### Verified public response summary

| Public HTTPS check | Observed result |
|---|---:|
| Authenticated liveness, readiness, and four aggregate endpoints | All six HTTP 200 |
| Missing authentication on those routes / invalid token | HTTP 401 |
| Overall response and 43 released breakdown rows | Match approved local bundle |
| Pipeline release metadata and artifact hashes | Match approved local bundle |
| Gold / eligible / excluded rows | 2,938 / 2,827 / 111 |
| Readmissions / provisional rate | 548 / 19.38% |
| Breakdown / released / suppressed rows | 51 / 43 / 8 |
| Unresolved reviews / master patients | 8 / 2,000 |
| Technical release / checks passed | PASS / 13 |
| Publication / current freshness at verification | FRESH / FRESH |
| Invalid query / POST / schema routes | 422 / 405 / 404 |
| Cache-Control / X-Content-Type-Options | no-store / nosniff |

The [safe machine-readable HTTP record](public-http-verification.json) preserves
the actual verification time, aggregate outcomes, and deployed code revision.
Render's editor removed the bundle's final newline; the mounted bytes were
independently checked and the exact provider digest was pinned. Neither identity
reviews nor historical results were changed. Protected local artifacts stayed
local; the public repository's pre-existing synthetic starter/test data is removed
from the final runtime build. Temporary diagnostics are removed from the normal
start command. Cloud Run deployment, Docker execution, production load testing,
per-user authorization, and clinical validation remain unverified.
