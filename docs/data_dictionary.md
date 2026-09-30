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
