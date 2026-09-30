# Data dictionary and layer contracts

## Official source schemas

| Dataset | Grain | Source columns |
|---|---|---|
| patients | One local hospital registration | `patient_id`, `source_system`, `first_name`, `last_name`, `date_of_birth`, `sex`, `phone`, `state` |
| admissions | One hospital stay source row | `admission_id`, `patient_id`, `hospital`, `admit_date`, `discharge_date`, `diagnosis_code`, `discharge_status` |
| lab_results | One reported test result | `lab_id`, `admission_id`, `test_name`, `result_value`, `unit`, `result_time` |

The official README defines `LG-xxxxxx` and `RSxxxxx` patient IDs, LG/RS source
systems, the four discharge statuses, and the three supported laboratory tests.

## Bronze lineage

Every accepted and structurally quarantined row has `_source_system`, `_source_file`,
`_source_row_number`, `_source_sha256`, `_ingested_at_utc`, and
`_ingestion_run_id`. Bronze retains source cells as strings without cleaning.

## Silver changes

- Patient dates become ISO dates and sex becomes `M` or `F`; names and phones are not
  transformed or exposed outside the protected Silver CSV.
- Admission dates become ISO dates, hospitals/statuses are canonicalized, and ICD-10
  is normalized lexically.
- Lab result timestamps become ISO datetimes; supported values are converted to the
  standard project units. Original lab value/unit and the conversion label are added.
- Bronze lineage is carried into every accepted Silver row and every rejected row.
- Per-dataset quarantine adds `_quarantine_reason_codes`.

See `silver.md` for the complete rule and reason-code contract.

## Phase 3 identity outputs

`patient_master.csv` keeps one row per local registration:

- `master_patient_id`: HMAC-derived network identity token.
- `patient_id`, `source_system`: protected local crosswalk.
- `link_status`: `AUTO_MATCHED`, `HUMAN_MATCHED`, `REVIEW_PENDING`,
  `REVIEW_REJECTED`, or `UNMATCHED`.
- `match_case_id`, `rule_version`: decision traceability.

`match_decisions.csv` records accepted automatic links and completed human decisions,
including local IDs, evidence/conflict codes, rule, reviewer metadata, and decision.

`review_queue.csv` records uncertain cross-hospital pairs with protected local IDs,
pseudonymous case IDs, evidence/conflict codes, score, rule, status, and reviewer
fields. It does not duplicate names, phones, or dates of birth.

`identity_audit.json` contains only aggregate counts, file hash/name, rule names,
configuration fingerprints, and reconciliation flags. See `matching_strategy.md` and
`human_oversight.md` for the governing contract.

## Phase 4 Gold output

`readmission_features.csv` has exactly one row per accepted Silver admission. It uses
the network `master_patient_id`, not a local patient ID. Its fields cover:

- index admission context: admission/master tokens, hospital, admission/discharge
  dates, age at admission, sex, three-character diagnosis group, discharge status,
  and length of stay;
- history known by the index admission: prior completed stays, prior 30/365-day stays,
  prior same-diagnosis stays, distinct prior hospitals, and days since prior discharge;
- index-stay glucose, haemoglobin, and creatinine count/first/latest/min/max/mean in
  the Phase 2 standard units;
- `readmitted_30d`, `label_status`, `observation_end_date`, and
  `feature_rule_version`.

Names, phones, local patient IDs, dates of birth, states, lab IDs, and next-admission
details are excluded. `readmission_feature_audit.json` contains aggregate counts,
source hashes, definitions, and privacy/scope exclusions only. See `gold.md`.

## Phase 5 aggregate outputs

`readmission_analytics.json` contains the eligible/excluded cohort reconciliation,
overall admission-level readmission rate and Wilson 95% interval, and nine governed
breakdowns. `readmission_breakdowns.csv` provides the same breakdowns in long form.
Both contain category-level aggregates only—never admission or master identifiers.

Each breakdown row contains the dimension/category, eligible/readmitted/not-readmitted
admission counts, rate, confidence bounds, and `suppression_reason`. All metric fields
are blank when a row is primarily or complementarily suppressed.

`readmission_analytics_audit.json` records the Gold input hash, output hashes, rule
version, release controls, aggregate row counts, and explicit privacy/scope exclusions.
See `analytics.md`.

## Phase 6 validation output

`release_validation.json` contains only aggregate release evidence:

- validation rule and overall `PASS` status;
- named checks with concise, non-sensitive details;
- Gold/eligible/excluded/breakdown/suppression reconciliation counts; and
- verified SHA-256 hashes for Gold and the two deterministic analytics reports.

It contains no patient or admission identifiers. See `validation.md`.

## PATIENTRA Core MVP output

`patientra_core_mvp.json` is an aggregate-only decision summary built from the governed
Silver admissions, Gold labels, Phase 3 identity audit, and Phase 5 analytics report.
It contains:

- before- and after-identity-matching readmission counts and rates on the same eligible
  admission cohort, plus the recovered hidden-readmission count;
- the highest released, unsuppressed diagnosis group and its aggregate rate; and
- automatic-match and human-review workload counts, including review outcomes.

The report also records rule versions and SHA-256 hashes for all four inputs. It contains
no local patient, admission, master-patient, or review-case identifier. See `core_mvp.md`.
