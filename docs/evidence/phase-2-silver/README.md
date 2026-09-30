# Phase 2 evidence — Silver cleaning

## Objective and controls

Create canonical patient, admission, and lab tables; fail closed on schema drift;
deduplicate deterministically; validate references/chronology; quarantine rejected
rows with reasons; and reconcile every source row. Profiles/audits contain aggregates
only.

## Verified outcome

- Patients: 2,304 source → 2,304 Silver + 0 quarantine.
- Admissions: 3,056 source → 2,938 Silver + 118 quarantine.
- Labs: 11,330 source → 10,231 Silver + 1,099 quarantine.
- All accepted dates, sex values, ICD-10 shapes, keys, references, units, and lab
  chronology passed post-run checks.
- Aggregate JSON contained none of the tested identifier values.

Detailed reasons and conversion counts are recorded in
`../../phase2-verification.md`; the rule contract and run commands are in
`../../silver.md` and the root README.
