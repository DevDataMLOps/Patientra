# Controlled synthetic live prototype

The local prototype at `/prototype` connects four views to a fresh validated run:
synthetic hospital CSVs → Bronze → Silver → identity → Gold → suppressed analytics
→ Phase 6 validation → aggregate API/dashboard → Phase 10 evaluation.

## Execute locally

From the repository root, with Python 3.11 or 3.12:

```powershell
python -m pip install -e ".[api,ml]"
python scripts/run_prototype.py
```

The command prepares a new run under the ignored `work/prototype/<uuid>` directory
and serves only `http://127.0.0.1:8765/prototype`. It prints the local token-file
path, not the token. Copy that file's contents into the page's connection field.
Swagger `/docs` and the aggregate dashboard `/dashboard` use the same local token.
Authorization is held only in browser memory and is never forwarded through links.

Use `--prepare-only` to build evidence without starting the server. Use
`--config <path>` to reopen an existing approved local release. New runs preserve
existing artifacts; the launcher does not execute cloud jobs, deploy to Render,
merge GitHub branches, or publish a release.

## Public hosted prototype

A separate Render Free web service serves the frozen synthetic release in
`demo_release/`. It installs only `.[api]` and starts with
`python -m patientra.prototype.hosting`, bound to `0.0.0.0:$PORT`.
The owner supplies a separate `PATIENTRA_HOSTED_DEMO_TOKEN` in Render; the local
token is not reused or published. Reviewers obtain the hosted token privately
from the maintainer and enter it in Connect or Swagger Authorize.

The public shell and `/healthz` contain no aggregate results or credentials.
Data endpoints remain bearer-authenticated and share a 60-request/minute budget.
The approved files are hash-verified on every request. The service has no database,
raw-record endpoint, pipeline trigger, model training, or inference endpoint.
The retained timestamps describe the frozen release; page refresh does not create
a new run. Free hosting can sleep and take time to wake.

Automatic deploys are disabled. New source commits require a deliberate maintainer
deployment. The existing `patientra-api` Render service remains a separate release.

## Views and actual fixture behavior

1. Pipeline: stage counts and Bronze = Silver + quarantine reconciliation.
2. Governance: all 13 individual release checks, quarantine counts, suppression,
   and the remaining unresolved review count.
3. Product: authenticated readmission metrics, Wilson intervals, unsuppressed
   breakdowns, local Swagger and dashboard, and separate existing Render links.
4. ML: logistic-regression/baseline evaluation, fixed temporal cutoff, 30-day
   training-label embargo, patient-disjoint holdout, train-only preprocessing,
   and unresolved-identity exclusions.

The deliberately patterned generator supplies 160 fictional patients and 200
accepted admissions/labs. An invalid patient, orphan admission, and invalid lab
produce three quarantined rows. A deliberately ambiguous cross-hospital pair
produces one unresolved review; the two associated admissions are excluded from
the ML cohort. They remain in the provisional Gold/analytics release as governed
by the existing contracts. No automatic human decision is manufactured.

Expected technical outcome: 200 Gold rows, 13 PASS checks, 10 released breakdowns,
four suppressed breakdowns, 100 training admissions, 98 holdout admissions,
zero shared master patients, and eight Phase 10 technical checks. Synthetic counts
describe this fixture only; they do not reproduce the historical hospital case study.

## Disclosure and provenance

The optional `/api/v1/prototype` endpoint reuses the base API bearer authentication,
shared rate budget, parameter restrictions, and no-store headers. Its strict typed
contract contains only projected scalar aggregates, approved check names, hashes,
and ML metrics. File SHA-256 verification and aggregate-bundle linkage happen on
every request. Changed artifacts, unknown fields, or mismatched counts fail closed.
No raw audits, patient/master identifiers, review worksheets, quarantine records,
suppressed category labels, trained models, or individual predictions are served.

The generated token protects this loopback synthetic demo and is stored only in
ignored local tooling files. A new source build is identified by its file hashes
in the delivered build record; the displayed base Git SHA does not claim that
uncommitted prototype additions were present in an earlier Databricks run.

The Databricks link refers to the separately verified October 2, 2026 development
job. The Render links refer to an independently deployed approved aggregate
release, which may differ or be stale. No synchronization or live cloud execution
is implied by those links. The existing Render service is unchanged.

`DEMONSTRATION_ONLY` is displayed throughout. Synthetic metrics validate mechanics,
not clinical utility, safety, calibration, generalization, or prospective accuracy.

## Verification

Run `python -m pytest -q`. Prototype tests exercise actual pipeline fixtures,
shared authentication/rate limiting, aggregate linkage, tampering, unknown fields,
and missing evidence. Browser checks cover all four views, wrong-token handling,
and clearing displayed results on disconnect. The source-only delivery excludes
credentials and runtime patient-level artifacts.
