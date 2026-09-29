# Phase 2 readiness gate

Do not begin Silver cleaning or patient matching until the following are available:

- Representative, authorized files from both hospitals plus delivery manifests.
- Data-owner dictionaries and clarification of grain, keys, timestamps, time zones,
  null conventions, diagnosis systems/versions, lab test identifiers, and units.
- Reconciliation totals and acceptance thresholds per file.
- A clinically approved mapping strategy for dates, sex values, diagnoses, labs, and
  invalid-record reason codes.
- A privacy-reviewed identity-resolution specification defining candidate generation,
  match evidence, thresholds, prohibited fields, false-merge risk, and audit trail.
- Named human reviewers, least-privilege review tooling, escalation routes, service
  levels, and a way to reverse an incorrect link.
- A precise readmission cohort and label definition, including transfers, deaths,
  planned admissions, observation stays, same-day events, boundary times, and leakage
  controls.

Recommended next deliverables are source-specific schema contracts, profiling reports
that expose no patient values, Silver validation rules, a pseudonymized identity map,
a human review queue, reconciliation tests, and a versioned Gold feature specification.

No quality rates, cross-hospital matches, hidden readmissions, labels, or model metrics
can be calculated before authorized real data and governance decisions exist.
