# Phase 1 evidence — Bronze ingestion

## Objective and controls

Preserve source cells unchanged while adding file hash, source file/system, physical
row number, UTC ingestion time, and run ID. Structural field-count errors are
reason-coded; outputs are atomic, overwrite-protected, restricted best-effort, and
Git-ignored.

## Verified official-file run

| File | SHA-256 | Accepted | Structural quarantine |
|---|---|---:|---:|
| patients.csv | `74f94e277f6c17f57d1cfdcfc65a97a2ac32160d975bc290cb26fb880def6496` | 2,304 | 0 |
| admissions.csv | `6fa069c3a3e88abf072884ec3d979177f0dab0f52e12b11fb28843ac6500c03a` | 3,056 | 0 |
| lab_results.csv | `028e602e771321aa520f137324ac3b322a3bb9c11cba21e5c25fdd6065b298b7` | 11,330 | 0 |

Post-run source hashes matched pre-run hashes. A source-field and row-lineage
comparison found zero mismatches. Phase 1 makes no clinical transformations.

## Reproduce

Use the three `patientra-ingest` commands in the root README, then run the test suite.
The current full suite contains 18 passing tests, including all original Bronze tests.
