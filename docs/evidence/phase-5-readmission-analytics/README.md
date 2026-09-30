# Phase 5 evidence — Readmission analytics

## Objective and acceptance boundary

Produce reproducible, admission-level readmission analytics from valid Phase 4 labels
without releasing patient/admission identifiers or small breakdown cells. Blank Gold
labels must remain excluded. Findings are descriptive and must not be presented as
causal, clinical, or patient-level risk conclusions.

## Verified official-file run

The verified run used `phase5-analytics-v1`, Gold observation end `2025-12-31`, and
minimum cell size 11.

| Measure | Result |
|---|---:|
| Gold admissions | 2,938 |
| Eligible admissions / master patients | 2,827 / 1,920 |
| Readmitted / not readmitted | 549 / 2,278 |
| Excluded admissions | 111 |
| Overall readmission rate | 19.42% |
| Wilson 95% confidence interval | 18.00%–20.92% |
| Breakdown dimensions / rows | 9 / 51 |
| Suppressed breakdown rows | 8 |

The excluded 111 admissions remain reconciled as 58 deaths, 30 without discharge,
and 23 with incomplete follow-up.

## Released descriptive findings

| Dimension | Category | Eligible | Readmitted | Rate (95% Wilson interval) |
|---|---|---:|---:|---:|
| Hospital | Lakeside General | 1,805 | 365 | 20.22% (18.43%–22.14%) |
| Hospital | Riverside Specialist | 1,022 | 184 | 18.00% (15.77%–20.48%) |
| Sex | F | 1,383 | 274 | 19.81% (17.80%–22.00%) |
| Sex | M | 1,444 | 275 | 19.04% (17.10%–21.15%) |
| Age | 65–79 | 683 | 175 | 25.62% (22.49%–29.03%) |
| Age | 80+ | 208 | 56 | 26.92% (21.35%–33.33%) |
| Diagnosis | I50 | 414 | 133 | 32.13% (27.81%–36.77%) |
| Diagnosis | J44 | 371 | 94 | 25.34% (21.18%–30.00%) |
| Diagnosis | N18 | 388 | 90 | 23.20% (19.27%–27.65%) |
| Discharge year | 2024 | 1,808 | 356 | 19.69% (17.92%–21.59%) |
| Discharge year | 2025 | 1,019 | 193 | 18.94% (16.65%–21.46%) |

These comparisons are unadjusted and admission-based. They do not establish that a
hospital, demographic characteristic, diagnosis, or year caused a difference.

Diagnosis `O80` was primarily suppressed and `K35` was complementarily suppressed.
Six monthly rows from July through December 2025 were primarily suppressed because at
least one outcome cell was below 11. No hidden values are reported here.

## Verification evidence

- The complete Phase 1–5 suite passes 29 tests.
- Overall counts independently reconcile to the Phase 4 label counts; all 111 blank
  labels remain excluded.
- Exact schema, unique ID, category, date, length-of-stay, label/status, observation-
  end, and feature-version checks fail closed.
- Primary and complementary suppression are tested with synthetic boundary cases.
- Fixed-input reports are byte-reproducible and intentional reruns preserve their
  hashes; the Gold input remains byte-unchanged.
- The aggregate JSON, CSV, and audit contain none of the actual admission or master
  identifier values.
- Outputs are atomic, overwrite-protected, and Git-ignored pending disclosure review.

Deterministic output hashes:

- `readmission_analytics.json`:
  `04d72cb00b774a2dcba7297e6c982829e418aaab56a6402ef220c949ba49ea09`
- `readmission_breakdowns.csv`:
  `4627b3c07d44941e8516e32d5cf12afce667c79786579f02923042dc997d2120`

The verified Gold input SHA-256 is
`0560061b8e62443b2be215786329267ec6edbd74288b74e8337b9aae714faecb`.

## Limitations and next gate

- Repeated admissions from the same master patient are not independent observations;
  confidence intervals are descriptive rather than a patient-clustered model.
- No risk adjustment, hypothesis testing, multiplicity correction, causal inference,
  model training, patient scoring, or clinical recommendation is performed.
- A separate approved modeling phase would require temporal train/validation design,
  fairness and calibration evaluation, clinical governance, and a defined use policy.
