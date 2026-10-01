# Changelog

All notable changes to PATIENTRA are documented here. Versions follow the project
phases rather than claiming production or clinical release readiness.

## Unreleased — Phase 8 controlled aggregate API

- Independently rebuilt and verified the provisional 548-readmission reconstruction,
  preserving eight pending identity reviews and separate historical results.
- Added a typed hosting bundle with local identity/Gold/release lineage checks;
  SQLite, patient rows, review queues, and matching secrets stay local.
- Added a non-root Cloud Run container, upload allowlist, Secret Manager deployment
  helper, host validation, and a per-process request limit.
- Verified hosted mode over local HTTP and extended the suite to 103 passing tests.
  Public deployment remains pending billing; no cloud build or remote HTTPS
  execution is claimed.
- Added optional FastAPI dependencies and a loopback-only `patientra-api` command.
- Added bearer-authenticated, read-only aggregate, unsuppressed breakdown, pipeline
  status, data-quality, liveness, and readiness endpoints.
- Added operator-pinned snapshot integrity, explicit schemas, reconciliation and
  suppression checks, bounded pagination, and sanitized error responses.
- Separated publication freshness from current analytics-run freshness and explicitly
  marked identity resolution and clinical accuracy as not assessed by the API.
- Documented actual local HTTP verification against the historical aggregate release,
  preserving the reconstructed Phase 7 governance limitation; 85 local tests passed.

## Unreleased — Phase 7 evidence documentation

- Added an aggregate-only local SQLite execution evidence summary covering reported
  publication, queries, validation, snapshot freshness, and serving responsibilities.
- Recorded the reconstructed 548-readmission result and eight unresolved identity
  reviews separately from the historical human-reviewed 549-readmission release.
- Distinguished corroborated historical audit counts from operator-attested Phase 7
  observations; documented technical `PASS` and publication-time `FRESH` limitations.
- Linked Phase 7 from the evidence index and repository README without publishing
  protected data or the serving database.

## 0.6.1 — Core MVP decision summary

- Added a reproducible aggregate-only command for the three headline business answers.
- Added same-cohort before/after identity-matching reconciliation and hidden-readmission
  recovery counts.
- Added source-hash lineage, fail-closed cross-phase checks, and three focused tests.

## 0.6.0 — Validation and presentation

- Added an independent 13-check release gate covering evidence, hashes, row and label
  reconciliation, suppression, identifier exclusion, and rule-version continuity.
- Added a validated eight-slide, aggregate-only stakeholder presentation.
- Completed a 31-test end-to-end automated suite.

## 0.5.0 — Readmission analytics

- Added admission-level rates and Wilson 95% confidence intervals.
- Added primary and complementary minimum-cell suppression.
- Added deterministic aggregate JSON/CSV reports and audit evidence.

## 0.4.0 — Gold feature engineering

- Added admission-grain, leakage-controlled demographic, encounter, diagnosis, and lab
  features.
- Added governed 30-day readmission labels with death, missing-discharge, and
  right-censoring statuses.

## 0.3.0 — Patient identity resolution

- Added high-confidence one-to-one automatic matching and protected human review.
- Added HMAC-derived master identifiers and reproducible crosswalk rebuilding.

## 0.2.0 — Silver data cleaning

- Added schema profiling, explicit date and code standardization, unit conversion,
  deduplication, and reason-coded quarantine.

## 0.1.0 — Bronze ingestion

- Added byte-level source hashes, row lineage, metadata-only manifests, structural
  quarantine, atomic writes, and overwrite protection.
