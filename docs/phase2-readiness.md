# Phase 2 decisions and next gate

The official starter README and all three expected synthetic datasets are now
available. Phase 2 implements and tests schema profiling, deterministic Silver
standardization, deduplication, quarantine, and reconciliation as documented in
`silver.md`.

Two interpretation choices remain explicit rather than embedded assumptions:

- Riverside slash dates are run as DMY based on unambiguous dataset-wide evidence.
- Riverside numeric sex codes are supplied as `1=M, 2=F` at runtime and require
  confirmation from the challenge data owner before production use.

Phase 3 now implements the required candidate generation, permitted comparison fields,
false-merge-first acceptance boundary, one-to-one constraint, protected review queue,
HMAC identifiers, reversibility, and aggregate audit. See `matching_strategy.md` and
`human_oversight.md`.

Do not create readmission labels until the cohort, transfer handling, death exclusion,
same-day/boundary behavior, planned admissions, timestamps, and leakage controls are
approved. Phases 1–3 still make no readmission outcome claims.
