# Phase 6 validation and presentation contract

## Release gate

`patientra-validate` independently checks the outputs and evidence from Phases 1–5.
It fails closed on a missing file, schema mismatch, hash mismatch, count mismatch,
identifier occurrence, malformed suppression, inconsistent version chain, or an
existing output that was not explicitly approved for overwrite.

The 13 checks cover:

1. Phase 1–5 evidence files;
2. the phase evidence index;
3. package version `0.6.1`;
4. Git-ignore rules for Gold and operational outputs;
5. Gold hash lineage into Phase 5;
6. analytics JSON/CSV hashes;
7. Gold row count and admission uniqueness;
8. Gold label/status reconciliation to the Phase 4 audit;
9. Phase 5 cohort/outcome reconciliation to Gold;
10. JSON/CSV breakdown equivalence;
11. suppression count and blank-metric integrity;
12. absence of actual Gold admission/master identifiers from analytics outputs; and
13. Phase 4–5 rule-version continuity.

## Presentation boundary

The Phase 6 presentation uses only tracked aggregate evidence and the validated
Phase 5 report. It contains no patient-level record, local ID, admission ID, master ID,
review case, name, phone number, date of birth, or hidden small-cell metric.

Charts and tables remain editable native PowerPoint objects. Speaker notes cite the
repository evidence used for each slide. The deck states that analytics are
descriptive and unadjusted and that validation does not authorize modeling or clinical
use.

## Run

```powershell
python -m patientra.validation --repository-root . --gold data/gold/readmission_features.csv --gold-audit data/gold/readmission_feature_audit.json --analytics-report outputs/phase5/readmission_analytics.json --analytics-breakdowns outputs/phase5/readmission_breakdowns.csv --analytics-audit outputs/phase5/readmission_analytics_audit.json --output outputs/phase6/release_validation.json
```

Use `--overwrite` only for an intentional rerun. Run the complete suite with:

```powershell
pytest --basetemp=work/pytest
```

The release gate validates data/repository evidence. It does not perform clinical
validation, causal inference, model validation, accessibility certification, or a
formal privacy determination.
