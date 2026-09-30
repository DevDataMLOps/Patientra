# PATIENTRA Core MVP contract

## Purpose

The Core MVP converts the governed Phase 3–5 evidence into exactly three business/demo
answers:

1. What is the 30-day readmission rate before versus after identity matching?
2. Which released diagnosis group has the highest readmission rate?
3. How many identity matches were automatic versus sent for human review?

Everything beyond those answers—dashboard, API, streaming, machine learning, and cloud
deployment—is an optional enhancement after this foundation is verified.

## Calculation contract

`patientra-mvp` reads the protected Silver admissions and Gold feature table plus the
aggregate Phase 3 identity audit and Phase 5 analytics report. It never edits an input.

- **Before matching** searches for a 0–30-day inclusive later admission using only the
  hospital-local `patient_id`.
- **After matching** uses the Gold label created from the governed network
  `master_patient_id`.
- Both rates use the identical Gold-eligible admission cohort and the same explicit
  observation end date.
- Hidden readmissions equal after-matching positives minus before-matching positives.
- The diagnosis answer is the highest rate among released, unsuppressed diagnosis rows.
- Match workload is read from the Phase 3 aggregate audit; “sent for review” is workload,
  not the number eventually accepted.

The command fails closed on schema drift, missing or duplicate identifiers, invalid ISO
dates, lost local-ID positives, inconsistent review counts, or disagreement with the
Phase 5 overall result.

## Run

```powershell
patientra-mvp --silver-admissions data/silver/admissions.silver.csv --gold data/gold/readmission_features.csv --identity-audit data/matching/identity_audit.json --analytics-report outputs/phase5/readmission_analytics.json --output outputs/mvp/patientra_core_mvp.json
```

Use `--overwrite` only for an intentional rerun. The output is deterministic for the
same inputs and includes the SHA-256 hash of each source.

## Privacy and interpretation boundary

The JSON report is aggregate-only. It contains no local patient ID, admission ID,
master-patient ID, review-case ID, name, phone, birth date, or row-level decision. These
synthetic case-study results demonstrate pipeline behavior; they are not clinical,
causal, production-matching, or generalizability claims.
