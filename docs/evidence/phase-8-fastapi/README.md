# Phase 8 evidence — Controlled aggregate FastAPI endpoints

## Objective and acceptance boundary

Expose approved aggregate analytics, pipeline status, and technical data-quality
metrics through an authenticated, read-only local FastAPI service. Phase 8 must
preserve suppression and the Phase 7 publication boundary without reading or
exposing patient-level inputs. No public deployment or clinical service is claimed.

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
filter, joined filter, unauthenticated schema, or public-host endpoints.

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
Its database and audits were unavailable for independent verification here.

`PASS` denotes the implemented technical release checks, not clinical accuracy or
complete identity resolution. Freshness measures analytics-run age, not hospital
record freshness. Data-quality endpoints do not measure source completeness,
quarantine rates, clinical validity, or identity-review completion.

The service uses one shared bearer credential and local loopback HTTP. It has no
per-user roles, TLS termination, production rate limiting, continuous monitoring,
or public deployment. These require separate engineering and governance approval.
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
unexpected files. Deployment preflight detected disabled billing and stopped
before changing cloud resources. **Public deployment and remote HTTPS verification
remain pending billing enablement.** No cloud image build or container execution
is claimed. See the [deployment contract](../../phase8-cloud-deployment.md).
