# Phase 2 Silver contract

## Scope

Phase 2 accepts only the three official Bronze schemas and fails closed on schema
drift. It standardizes values, validates keys and chronology, deduplicates local
records, and creates per-table quarantine files. It does not compare identities
across hospitals and does not calculate readmission outcomes.

## Interpretation choices

- ISO `YYYY-MM-DD` dates are parsed directly.
- Slash dates require `--slash-date-order dmy` or `mdy`; the default is `reject`.
- This starter delivery was run as DMY because 1,879 rows provide unambiguous
  day-first evidence and none provide month-first evidence.
- `M`, `Male`, `F`, and `Female` normalize directly. Numeric codes require repeated
  `--numeric-sex-code CODE=M|F` arguments. The verified local run used `1=M, 2=F`;
  this codebook still requires data-owner confirmation before production.
- ICD-10 values are trimmed, uppercased, stripped of an existing dot/spacing, checked
  against the project lexical shape, and rendered with a dot after character three.
  There is no clinical remapping to a different diagnosis.

## Laboratory conversions

| Test | Accepted source unit | Silver unit | Formula |
|---|---|---|---|
| glucose | `mg/dL` | `mg/dL` | unchanged |
| glucose | `mmol/L` | `mg/dL` | value × 18.016 |
| haemoglobin/hemoglobin | `g/dL` | `g/dL` | unchanged |
| haemoglobin/hemoglobin | `g/L` | `g/dL` | value ÷ 10 |
| creatinine | `mg/dL` | `mg/dL` | unchanged |
| creatinine | `umol/L`, `µmol/L`, `μmol/L` | `mg/dL` | value ÷ 88.4 |

Decimal arithmetic is used and results are rounded to at most six decimal places.
The original value and unit are retained in `result_value_original` and
`unit_original`; `conversion_applied` identifies the formula.

## Deduplication and integrity

- A repeated primary key with identical source fields keeps its first occurrence and
  quarantines later occurrences as `duplicate_record`.
- Every version of a repeated primary key with conflicting fields is quarantined as
  `duplicate_primary_key_conflict`; no arbitrary winner is selected.
- Admissions must reference an accepted Silver patient.
- Lab results must reference an accepted Silver admission.
- Discharge cannot precede admission. A blank discharge is valid only for
  `still_admitted`. Lab result dates must fall within the linked admission period
  when a discharge date exists.

## Quarantine reason codes

Reason codes are semicolon-separated when a row violates more than one rule.

- Key/reference: `missing_patient_id`, `missing_admission_id`, `missing_lab_id`,
  `unknown_patient_id`, `unknown_admission_id`, `duplicate_record`,
  `duplicate_primary_key_conflict`, `patient_id_source_mismatch`.
- Dates/chronology: `missing_*`, `invalid_*`, `unconfigured_slash_date_*`,
  `discharge_before_admission`, `unexpected_discharge_date_for_still_admitted`,
  `result_before_admission`, `result_after_discharge`.
- Categories/codes: `invalid_source_system`, `invalid_sex`,
  `unmapped_numeric_sex_code`, `invalid_hospital`, `invalid_discharge_status`,
  `invalid_diagnosis_code`.
- Labs: `unsupported_test_name`, `invalid_result_value`, `unsupported_test_unit`.

The audit JSON includes source, Silver, and quarantine row counts; reason counts;
transformation/conversion counts; configuration; scope exclusions; and a reconciliation
flag. It contains no names, phone numbers, patient IDs, admission IDs, or lab IDs.

## Privacy boundary

Patient names and phone numbers remain unchanged inside the access-controlled Silver
patient table because Phase 3 may need them under a separately approved matching
specification. They never enter profiles, audit JSON, logs, or Git. Gold-layer removal
of direct identifiers is future work and is not represented as complete here.
