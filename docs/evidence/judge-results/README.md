# Judge results — verified matching impact

## Headline results

| Measure | Verified result |
|---|---:|
| Readmission rate before identity matching | 17.90% |
| Readmission rate after identity matching | 19.42% |
| Cross-hospital readmissions hidden by local IDs | 43 |
| Highest-readmission diagnosis group | I50 — 32.13% |
| High-confidence automatic matches | 304 |
| Human-review matches | 8 |

## Derivation

The comparison holds the Phase 4/5 eligible cohort fixed at 2,827 admissions and changes
only the identity key used to find a qualifying later admission.

- **Before matching:** readmission is searched only within the same hospital-local
  `patient_id`. This produces 506 positive labels, or 17.90%.
- **After matching:** readmission is searched across the Phase 3
  `master_patient_id`, including accepted cross-hospital links. This produces 549
  positive labels, or 19.42%.
- **Hidden readmissions:** 43 admissions are positive after master-identity resolution
  but not under the local-ID-only calculation. No local-ID positive becomes negative
  after matching.
- **Highest diagnosis group:** I50 has 133 readmissions among 414 eligible admissions,
  or 32.13%, the highest released unsuppressed diagnosis-group rate.

Both label calculations use the same Phase 4 rule: another admission from 0 through 30
calendar days inclusive after index discharge, bounded by the `2025-12-31` observation
end. Death, missing-discharge, and incomplete-follow-up handling remains unchanged.

## Identity-resolution evidence

Phase 3 produced 304 high-confidence automatic pairs and routed 8 plausible conflicting
pairs through the protected human-review contract. All eight were reviewed; four were
accepted and four were rejected. The Judge Results line reports review workload, not
eight accepted links.

## Interpretation boundary

The 1.52 percentage-point increase demonstrates the analytical effect of governed
cross-hospital identity resolution in this synthetic case study. It does not establish
causality, clinical risk, production matching accuracy, or generalizability to another
population. All figures are aggregate; no admission, patient, or master identifiers are
published.
