# Phase 4 Gold feature and label contract

## Grain and cohort

`data/gold/readmission_features.csv` contains one row for every accepted Silver
admission. The verified official run uses all 2,938 Silver admissions. Phase 3
`master_patient_id` values join local registrations across hospitals; rejected pairs
remain separate. The observation end is explicit and an admission starting after it
causes the run to fail rather than silently using future evidence.

## Label definition

`readmitted_30d = 1` when the same master patient has another admission at either
hospital from 0 through 30 calendar days inclusive after the index discharge.
Otherwise it is `0` only when the full 30-day window is observable.

| `label_status` | `readmitted_30d` | Meaning |
|---|---:|---|
| `labeled_positive` | `1` | A qualifying later admission was observed by the cutoff. |
| `labeled_negative` | `0` | No qualifying admission and all 30 follow-up days are observable. |
| `excluded_died` | blank | The patient died during the index stay, per the case study. |
| `excluded_no_discharge` | blank | The stay has no discharge from which to start the window. |
| `censored_incomplete_30d_followup` | blank | No event was observed, but fewer than 30 follow-up days are available. |

A positive observed before the cutoff remains positive even when the remainder of its
30-day window is incomplete. The Gold table does not expose the later admission ID,
date, hospital, or gap; those are outcome evidence, not predictors.

## Feature timing

Features describe the index stay at discharge and history available by the index
admission. History counts only completed stays whose discharge is on or before the
index admission date. Laboratory summaries use only Silver lab results validated to
fall within the index stay. No next-admission information is included.

| Feature family | Fields |
|---|---|
| Identity/grain | `admission_id`, `master_patient_id` |
| Index encounter | `hospital`, `admit_date`, `discharge_date`, `diagnosis_group`, `discharge_status`, `length_of_stay_days` |
| Demographic | `age_at_admit`, `sex` |
| Prior utilization | `prior_completed_admission_count`, `prior_admission_30d_count`, `prior_admission_365d_count`, `prior_same_diagnosis_group_count`, `prior_distinct_hospital_count`, `days_since_prior_discharge` |
| Index-stay labs | glucose, haemoglobin, and creatinine `count`, `first`, `latest`, `min`, `max`, and `mean` |
| Governance | `readmitted_30d`, `label_status`, `observation_end_date`, `feature_rule_version` |

The diagnosis group is the first three ICD-10 characters, as specified in the case
study. Lab values are already standardized by Phase 2 to mg/dL for glucose and
creatinine and g/dL for haemoglobin. Decimal summaries are deterministically rounded
to three places.

## Privacy and boundaries

The Gold table excludes names, phones, local patient IDs, dates of birth, states, lab
IDs, and future-admission details. Admission and master tokens are still sensitive;
the table remains Git-ignored and must stay access-controlled. The audit is
aggregate-only and contains input hashes, counts, definitions, and rule metadata.

Phase 4 does not train a model, calculate risk scores, interpret readmission rates, or
perform diagnosis outcome analysis. Those are Phase 5 activities.

## Run

From the repository root after Phases 2 and 3 are complete:

```powershell
python -m patientra.features --patients data/silver/patients.silver.csv --admissions data/silver/admissions.silver.csv --lab-results data/silver/lab_results.silver.csv --patient-master data/matching/patient_master.csv --observation-end 2025-12-31 --output-dir data/gold
```

If the package is installed, `patientra-gold` accepts the same arguments. Existing
outputs are protected; add `--overwrite` only for an intentional rebuild.

Run all reproducible checks with:

```powershell
pytest --basetemp=work/pytest
```
