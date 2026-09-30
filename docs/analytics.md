# Phase 5 readmission analytics contract

## Analytical cohort

Phase 5 reads the exact Phase 4 Gold schema and analyzes only rows whose
`label_status` is `labeled_positive` or `labeled_negative`. Deaths, stays without a
discharge, and incomplete 30-day follow-up remain excluded and are never converted to
negative outcomes. Rates are admission-level, not patient-level.

The pipeline fails closed on schema drift, duplicate admission IDs, inconsistent
labels/statuses, invalid dates or stay lengths, unsupported categories, mixed
observation ends, or mixed Gold rule versions.

## Metrics

The overall report includes eligible, readmitted, and not-readmitted admission counts,
the readmission percentage, and a two-sided Wilson 95% confidence interval. The same
metrics are produced for:

- hospital;
- sex;
- age band;
- three-character diagnosis group;
- discharge status;
- prior completed-admission band;
- length-of-stay band;
- discharge year; and
- discharge month.

These are descriptive associations. Differences between categories may reflect case
mix, repeated admissions, data-generation patterns, confounding, or chance. They do
not establish causes, treatment effects, clinical risk, or recommended action.

## Disclosure control

The default `minimum_cell_size` is 11. A breakdown row is primarily suppressed if its
eligible denominator, positive count, or negative count is below that threshold. When
exactly one group in a dimension is primarily suppressed, the smallest remaining
publishable group is complementarily suppressed so the hidden count cannot be derived
directly from the overall total.

Suppressed rows retain only the dimension, category, and reason; all counts, rate, and
confidence bounds are blank. Reports exclude admission IDs, master patient IDs, names,
phones, birth dates, local IDs, and lab IDs. Suppression reduces disclosure risk but
is not a formal de-identification determination.

## Outputs

- `outputs/phase5/readmission_analytics.json`: deterministic cohort, overall metrics,
  and breakdowns.
- `outputs/phase5/readmission_breakdowns.csv`: deterministic long-form breakdowns.
- `outputs/phase5/readmission_analytics_audit.json`: run metadata, input/output hashes,
  release controls, and scope/privacy exclusions.

All three are Git-ignored by default pending disclosure review.

## Run

```powershell
python -m patientra.analytics --gold data/gold/readmission_features.csv --output-dir outputs/phase5 --minimum-cell-size 11
```

If installed, `patientra-analytics` accepts the same arguments. Existing outputs are
protected; add `--overwrite` only for an intentional rebuild.

```powershell
pytest --basetemp=work/pytest
```
