# PATIENTRA five-minute demo

This walkthrough is designed for judges, reviewers, and technical stakeholders. It uses
repository evidence and synthetic tests only; protected operational files are not opened.

## 0:00–0:45 — Frame the problem

Open the root README and explain the challenge: two hospitals provide inconsistent CSVs,
patient identities overlap, and readmission analytics must be reproducible without
publishing patient-level data.

Point to the architecture diagram and the fail-closed path to quarantine or human review.

## 0:45–1:45 — Prove the data foundation

Open the [evidence index](evidence/README.md):

- Phase 1 proves exact source preservation, hashes, and lineage.
- Phase 2 proves explicit cleaning choices, conversion rules, deduplication, and row
  reconciliation.
- Phase 3 proves conservative one-to-one identity resolution and reviewed uncertainty.

Emphasize that patient-level working files are Git-ignored and no source rows are shown.

## 1:45–3:00 — Explain Gold and analytics

Open the [Gold contract](gold.md) and [analytics methodology](analytics.md):

- one row per accepted Silver admission;
- an explicit observation cutoff and blank labels for excluded or censored rows;
- 2,827 eligible admissions and 549 readmissions;
- an overall admission-level rate of 19.42% with a Wilson 95% interval; and
- primary plus complementary suppression for small cells.

State clearly that these are descriptive associations, not causal or clinical claims.

## 3:00–4:00 — Demonstrate verification

Run the synthetic test suite:

```powershell
python -m pytest -q --basetemp work/pytest
```

Expected result: `34 passed`.

Then show the [Phase 6 evidence](evidence/phase-6-validation-presentation/README.md):

- 13 of 13 release checks passed;
- all Gold and analytics counts reconcile;
- 8 breakdown rows are suppressed; and
- the identifier scan found zero hits in analytics outputs.

## 4:00–5:00 — Close with the Core MVP decision story

Run `patientra-mvp` or open the Core MVP evidence and state the three answers: the
readmission rate moves from 17.90% to 19.42% after identity matching, I50 is the highest
released diagnosis group at 32.13%, and identity resolution routed 304 matches
automatically with 8 sent for human review.

Open the [stakeholder presentation](presentation/PATIENTRA_Phase6_Validation_Presentation_Final.pptx).
Summarize how PATIENTRA converts fragmented hospital extracts into defensible aggregate
readmission intelligence while keeping identity decisions reviewable and every published
claim traceable to evidence.

Close with the scope boundary: future patient-level prediction requires a separate
approved modeling, fairness, leakage, and clinical-governance phase.
