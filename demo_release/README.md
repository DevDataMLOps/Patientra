# Frozen synthetic demonstration release

These three JSON files contain **only approved synthetic aggregates and Phase 10
evaluation metrics** for run `fbb8e1b0-915d-42a8-9054-acefbbb76bb8`.
The local pipeline generated 200 Gold admissions, 13 PASS checks, three quarantined
records, four suppressed groups, and one unresolved identity review. The ML split
has 100 training and 98 holdout admissions with zero shared master patients.

`config.json` pins both aggregate artifacts by SHA-256. The hosted API validates
the hashes and their cross-artifact linkage on startup and every request. No raw
patient data, identity crosswalk, review worksheet, quarantine record, suppressed
group label, individual prediction, trained model, or bearer token is included.

The synthetic release is frozen; hosting does not regenerate the delivery or run
Databricks. Its original timestamps remain visible and its freshness ages normally.
Refreshing the website reads the same approved snapshot. A replacement release
requires a separately generated and validated snapshot and reviewed source change.

Start on Render with `python -m patientra.prototype.hosting`, a separate secret
`PATIENTRA_HOSTED_DEMO_TOKEN`, and the provider's `RENDER_EXTERNAL_HOSTNAME`/`PORT`.
Install only `.[api]`; hosted serving does not require scikit-learn or a database.
