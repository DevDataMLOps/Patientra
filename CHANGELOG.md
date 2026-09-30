# Changelog

All notable changes to PATIENTRA are documented here. Versions follow the six project
phases rather than claiming production or clinical release readiness.

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
