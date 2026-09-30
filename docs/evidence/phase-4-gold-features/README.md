# Phase 4 evidence — Gold feature engineering

## Objective and acceptance boundary

Create `gold.readmission_features` at one row per accepted Silver admission, using the
Phase 3 master identity for cross-hospital 30-day readmission labels. Direct identity
fields and future-event details must not enter predictors. Death, no-discharge, and
right-censored records must remain auditable rather than being mislabeled negative.

## Verified official-file run

The verified run used observation end `2025-12-31` and rule
`phase4-gold-v1`.

| Measure | Result |
|---|---:|
| Silver patients / patient-master rows | 2,304 / 2,304 |
| Master identities / represented in Gold | 1,996 / 1,968 |
| Silver admissions / Gold rows / unique admission IDs | 2,938 / 2,938 / 2,938 |
| Silver lab results | 10,231 |
| Positive / negative / unlabeled labels | 549 / 2,278 / 111 |
| Excluded died / no discharge / right-censored | 58 / 30 / 23 |
| Rows with glucose / haemoglobin / creatinine | 2,358 / 2,344 / 2,379 |
| Positive gap range | 2–29 days |
| Cross-hospital positive events | 44 |
| Same-day or overlapping admission ambiguity | 0 pairs |

The deterministic Gold CSV SHA-256 is
`0560061b8e62443b2be215786329267ec6edbd74288b74e8337b9aae714faecb`.
Input hashes stored in the aggregate audit are:

- patients: `3840a145be72f0b820a9f69331eec53dd0851af45c938621cda8e92155a7192d`
- admissions: `07008c0206e1d5388113c175bb0d59d3f445989eefd02f9bbb14ae7586028ead`
- lab results: `dc924f129513d80d91cf3a37fe6801ab84ce0335ebc6da94111413f1c0e7e900`
- patient master: `456b94e29d9e4936e78507f56b80887da14864fd50744879c87f5eab7d857ebe`

## Verification evidence

- The complete Phase 1–4 suite passes 25 tests, including both day 0 and day 30 of
  the inclusive readmission boundary.
- Exact schema validation, master coverage, unique keys, supported labs, canonical
  dates, stay chronology, and observation-cutoff compliance fail closed.
- A fixed-input/fixed-metadata rerun is byte-reproducible; the real Gold CSV hash was
  unchanged across intentional reruns.
- Every accepted Silver admission reconciles to exactly one Gold row.
- Independent label reconciliation confirmed 549 qualifying events, all within the
  inclusive 0–30-day contract and no post-cutoff evidence.
- No forbidden identity or future-event columns appear in the 38-column Gold schema.
- Tested patient names, phones, local IDs, and lab IDs do not occur in the Gold CSV or
  aggregate audit.
- Outputs are atomic, protected from accidental overwrite, and Git-ignored. Silver,
  matching, Bronze, and raw inputs are opened read-only and are never rewritten.

## Limitations

- The case study provides dates rather than times for admissions/discharges. The
  verified data contains no same-day or overlapping pairs, so ordering is unambiguous;
  a future delivery with such pairs needs an approved ordering rule.
- The explicit cutoff controls outcome observability. Four index-stay lab results fall
  after the cutoff for stays continuing beyond it; those rows are unlabeled and the
  labs remain valid discharge-time features, not outcome evidence.
- Admission/master tokens remain sensitive even though direct identifiers are absent.
  The patient-level Gold CSV is not a public deliverable.

## Next gate

Phase 5 may analyze only rows with `labeled_positive` or `labeled_negative`, preserve
the Phase 4 exclusion/censoring rules, and define train/validation timing before model
development. It must not treat blank labels as negative.
