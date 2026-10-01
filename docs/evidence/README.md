# PATIENTRA phase evidence index

## Judge-ready result

The [Judge Results evidence](judge-results/README.md) reconciles the local-ID-only and
master-identity readmission calculations and documents the headline diagnosis and
matching workload without publishing identifiers.

Evidence is aggregate-only and safe for repository review. Patient-level raw, Bronze,
Silver, matching, and quarantine CSVs remain Git-ignored. Screenshots containing
individual records are intentionally excluded.

| Phase | Evidence | Status |
|---|---|---|
| 1 — Bronze ingestion | `phase-1-bronze/README.md` | Complete |
| 2 — Silver cleaning | `phase-2-silver/README.md` | Complete |
| 3 — Identity resolution | `phase-3-identity-resolution/README.md` | Complete; 8 human reviews applied (4 accepted, 4 rejected) |
| 4 — Gold features and label | `phase-4-gold-features/README.md` | Complete |
| 5 — Readmission analytics | `phase-5-readmission-analytics/README.md` | Complete |
| 6 — Validation and presentation | `phase-6-validation-presentation/README.md` | Complete |
| 7 — Serving and snapshot observability | [Phase 7 evidence](phase-7-serving-observability/README.md) | Original run operator-attested; subsequent reconstruction verified; 8 reviews unresolved |
| 8 — Controlled FastAPI endpoints | [Phase 8 evidence](phase-8-fastapi/README.md) | Historical and reconstructed local HTTP execution verified; 104 tests passed; Render public HTTPS aggregates verified; 8 identity reviews unresolved |

Phase 9: [Controlled dashboard evidence](phase-9-dashboard/README.md) records the
same-origin authenticated aggregate browser view and its verification.

Phases 1–6 record the historical human-reviewed release. Phase 7 documents a
separate reconstructed local run (548 readmissions rather than the historical 549).
Its evidence provenance and independent-verification limitations are explicit;
the unresolved reviews do not revise the historical Phase 3 decisions.
Phase 8's live HTTP verification uses the available historical aggregate release;
it does not independently verify the reconstructed Phase 7 snapshot.
The hosting follow-up verifies a newly rebuilt reconstruction with matching
aggregates; it does not retrospectively verify the original operator artifact.

Each completed phase records scope, inputs, controls, verified outcomes, tests, privacy
evidence, limitations, and the gate for the next phase.
