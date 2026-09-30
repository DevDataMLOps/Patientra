# Phase 2 verified run — 2026-09-29

This report contains aggregate counts only. The raw, Bronze, Silver, and quarantine
CSVs remain Git-ignored local data.

## Input integrity and Bronze

| File | SHA-256 | Source rows | Bronze accepted | Bronze quarantined |
|---|---|---:|---:|---:|
| patients.csv | `74f94e277f6c17f57d1cfdcfc65a97a2ac32160d975bc290cb26fb880def6496` | 2,304 | 2,304 | 0 |
| admissions.csv | `6fa069c3a3e88abf072884ec3d979177f0dab0f52e12b11fb28843ac6500c03a` | 3,056 | 3,056 | 0 |
| lab_results.csv | `028e602e771321aa520f137324ac3b322a3bb9c11cba21e5c25fdd6065b298b7` | 11,330 | 11,330 | 0 |

The post-run hashes matched the pre-run hashes. A field-by-field comparison of raw
source columns to Bronze plus source-row lineage found zero mismatches.

## Silver reconciliation

| Dataset | Source | Silver | Quarantine | Reconciled |
|---|---:|---:|---:|---:|
| patients | 2,304 | 2,304 | 0 | yes |
| admissions | 3,056 | 2,938 | 118 | yes |
| lab_results | 11,330 | 10,231 | 1,099 | yes |

Admission reason counts were 43 `duplicate_record`, 30
`duplicate_primary_key_conflict` (all versions of 15 conflicting keys), and 45
`discharge_before_admission`. Lab reason counts were 866 `result_after_discharge`
and 233 `unknown_admission_id` after invalid/conflicting admissions were excluded.

## Transformation counts

- 879 patient slash dates standardized to ISO; final sex counts were 1,145 `F` and
  1,159 `M`.
- 1,072 accepted admission dates standardized from slash format to ISO; 529 accepted
  diagnosis codes required lexical reformatting.
- Lab conversions: 1,244 glucose `mmol/L × 18.016`, 1,230 haemoglobin `g/L ÷ 10`,
  1,280 creatinine `umol/L ÷ 88.4`, and 6,477 already-standard values unchanged.

## Verification checks

- 13 tests passed, including all Phase 1 tests and new profiling/Silver tests.
- Python compilation completed without errors.
- Silver contained no invalid patient/admission date shapes, invalid sex values,
  invalid ICD-10 lexical shapes, duplicate primary keys, unknown accepted references,
  noncanonical lab test/unit pairs, or lab chronology violations.
- Aggregate profile/audit JSON did not contain tested patient, admission, or lab
  identifier values.
- `git diff --check` reported no whitespace errors.

Run configuration: `--slash-date-order dmy --numeric-sex-code 1=M
--numeric-sex-code 2=F`. The DMY selection is supported by unambiguous file evidence;
the numeric sex codebook remains an explicit configuration requiring data-owner
confirmation before production use.
