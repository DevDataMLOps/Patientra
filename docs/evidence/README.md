# PATIENTRA phase evidence index

Evidence is aggregate-only and safe for repository review. Patient-level raw, Bronze,
Silver, matching, and quarantine CSVs remain Git-ignored. Screenshots containing
individual records are intentionally excluded.

| Phase | Evidence | Status |
|---|---|---|
| 1 — Bronze ingestion | `phase-1-bronze/README.md` | Complete |
| 2 — Silver cleaning | `phase-2-silver/README.md` | Complete |
| 3 — Identity resolution | `phase-3-identity-resolution/README.md` | Complete; 8 human reviews applied (4 accepted, 4 rejected) |
| 4 — Gold features and label | Not started | Pending |
| 5 — Readmission analysis | Not started | Pending |

Each completed phase records scope, inputs, controls, verified outcomes, tests, privacy
evidence, limitations, and the gate for the next phase.
