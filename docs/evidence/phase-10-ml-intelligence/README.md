# Phase 10 evidence — ML intelligence

## Objective and completion boundary

Execute a reproducible, local **readmission-risk demonstration**, compare a learned
model with a simple baseline, and publish honest aggregate evaluation evidence.
The implementation, executed experiment, tests and model card complete this
demonstration phase. Clinical validation and public individual inference are
outside the completed scope. See the [implementation contract](../../phase10-ml.md)
and [actual execution report](execution-report.json).

## Model card

| Item | Implemented behavior |
|---|---|
| Intended use | Synthetic case-study demonstration of a governed ML experiment |
| Prediction time | Index admission discharge; diagnosis/discharge fields assumed available |
| Target | Existing Gold 0–30-day inclusive readmission label |
| Learned model | Logistic regression; fixed settings, no tuning on holdout |
| Reference | Constant probability equal to training readmission prevalence |
| Features | 8 numeric and 4 categorical discharge/prior-history fields |
| Exclusions | Identifiers, outcome/status fields, calendar dates and lab summaries |
| Identity control | Exclude all master identities awaiting review |
| Split | Fixed 2025-01-01 cutoff, full training-label maturity, no shared master IDs |
| Output | Aggregate JSON with source/implementation hashes and runtime versions |
| Release | `DEMONSTRATION_ONLY`; clinical accuracy `NOT_ASSESSED` |

All models and admission-level probabilities are ephemeral in-memory values.
No model serialization, individual predictions, risk API, or public ML deployment
is produced. Existing descriptive API/dashboard aggregates remain separate.

## Verified execution

The execution report records the actual UTC run time, actual source hashes and
runtime versions. It was produced from the available **reconstructed** local Gold,
master and audits, rather than the historical human-reviewed release. The master
hash matches the Gold audit and cohort/status counts reconcile.

| Cohort/control | Observed result |
|---|---:|
| Gold admission rows | 2,938 |
| Gold eligible admissions / observed readmissions | 2,827 / 548 |
| Gold excluded label rows | 111 |
| Eligible admissions excluded for pending identity | 24 |
| Time-boundary or incomplete-follow-up exclusions (combined) | 204 |
| Future admissions excluded because patient appears in training | 200 |
| Training admissions / master patients / positives | 1,638 / 1,260 / 319 |
| Held-out admissions / master patients / positives | 761 / 551 / 149 |
| Shared master patients across training/test | 0 |
| Unresolved review cases | 8 |

Training requires discharge plus 30 days **strictly before** the cutoff. Holdout
admissions begin on/after the cutoff and cannot belong to a training master identity.
Both cohorts require complete follow-up and at least 11 admissions in each outcome
class. Individual pending identities are excluded, without applying review decisions.
The combined exclusion count preserves the cohort reconciliation while avoiding
publication of a specific small incomplete-follow-up count:
`2,827 = 24 + 204 + 200 + 1,638 + 761`.

## Held-out model performance

| Metric | Logistic regression | Training-prevalence baseline | Direction |
|---|---:|---:|---|
| ROC AUC | 0.695453 | 0.500000 | Higher |
| Average precision | 0.329779 | 0.195795 | Higher |
| Brier score | 0.147278 | 0.157460 | Lower |
| Log loss | 0.460957 | 0.494521 | Lower |
| Balanced accuracy at threshold 0.5 | 0.500000 | 0.500000 | Higher |

The learned model improves ranking and probability-error metrics on this synthetic
holdout. It provides **no balanced-accuracy improvement at the fixed 0.5 threshold**.
That threshold was not clinically selected. Better ranking is not a claim of useful
clinical decisions, causal effects, externally calibrated risk or generalizability.
Confusion matrices for both models are nullified because at least one cell is below
the minimum size of 11. No suppressed cells or individual scores are published.

## Validation and reproducibility

- The complete automated suite passed **113 tests**, including eight new ML tests.
  One existing upstream Starlette/HTTPX deprecation warning remains.
- Tests cover pending-identity exclusion, master-hash lineage failure, temporal
  embargo, patient separation, undersized outcome classes, train-only preprocessing,
  unknown future categories, protected-field exclusion, nonfinite/negative inputs,
  sanitized CLI failures, confusion-cell suppression and complete follow-up.
- End-to-end tests verify source immutability, aggregate-only output, overwrite
  protection, deterministic reruns and preservation of earlier output on nonconvergence.
- Two actual same-input reconstruction runs produced identical reports after removing
  the execution timestamp. Their metrics, source hashes, split and configuration agree.
- Source compilation, dependency consistency (`pip check`) and `git diff --check` passed.

The local report records Python 3.11.9 and scikit-learn 1.7.2 plus actual NumPy,
SciPy, joblib and threadpoolctl versions. The ML extra is optional; the CI test
installation includes it. GitHub CI results belong to the PR check history and are
not fabricated as local execution outcomes.

## Privacy and governance

**Eight patient identity-review cases remain unresolved.** Excluding their identities
does not adjudicate them or establish complete identity resolution. The local demo
ABSTAIN worksheet remains unapplied. No patient-level source/Gold CSVs, master files,
review queues, review decisions, matching secrets, serving database, trained artifacts
or admission-level predictions are included in this evidence or Git delivery.

The reconstructed release has **548** observed readmissions, compared with **549**
in the historical human-reviewed release; these releases are not identical. Phase 10
does not rewrite earlier results. Technical ML checks and the earlier serving `PASS`
do not establish clinical accuracy. Earlier `FRESH` status concerns analytics-run
recency at the stated execution, not freshness of underlying hospital records.

Performance is limited to synthetic data and a future cohort of patients unseen
in training under provisional master identities. Automatic links have not been
clinically certified. Multiple admissions for the same holdout patient are correlated.
Source field availability, external/prospective validation, returning-patient
performance, subgroup fairness, confidence intervals, clinical calibration and
clinical threshold selection remain unverified. Public ML inference is not deployed.
