# PATIENTRA — Trusted data and readmission feature foundation

Reproducible, privacy-conscious data preparation for the fictional Lakeside Health
Network readmission challenge. Phase 1 preserves the provider delivery in Bronze;
Phase 2 profiles and cleans the official `patients`, `admissions`, and `lab_results`
schemas into governed Silver tables with reason-coded quarantine. Phase 3 creates a
conservative cross-hospital `patient_master` and protected human review queue. Phase 4
creates a leakage-controlled, admission-grain Gold feature table with an auditable
30-day readmission label. Phase 5 produces disclosure-controlled aggregate readmission
analytics with confidence intervals and small-cell suppression. Phase 6 adds an
end-to-end release gate and an aggregate-only stakeholder presentation.

> The official starter data is synthetic, but names, phone numbers, local IDs, and
> linked records are handled as if they were patient information. Raw, Bronze, Silver,
> quarantine, and ad-hoc outputs are ignored by Git and never printed by the pipeline.

## What is implemented

- Byte-level SHA-256 lineage, source row numbers, ingestion run IDs, metadata-only
  manifests, structural quarantine, atomic writes, and overwrite protection in Bronze.
- Metadata-only schema profiles: row/column counts, missing counts, distinct counts,
  duplicate counts, and hashes, with no samples or cell values.
- Explicit date parsing. ISO dates are accepted directly; slash dates are rejected
  unless the operator supplies `dmy` or `mdy`.
- Sex standardization to `M`/`F`, with numeric codes rejected unless an explicit
  codebook is supplied.
- ICD-10 lexical normalization: uppercase and a decimal after the first three
  characters, without clinical recoding.
- Project-specified unit conversions: glucose `mmol/L × 18.016`, haemoglobin
  `g/L ÷ 10`, and creatinine `umol/L ÷ 88.4`.
- Deterministic primary-key deduplication, referential checks, chronology checks,
  reason-coded quarantine, and source/Silver/quarantine reconciliation.
- Tests for conversions, ambiguous formats, duplicate/conflicting keys, quarantine,
  schema drift, privacy-safe profiling, and the Phase 1 contract.
- Cross-hospital candidate blocking, high-confidence one-to-one automatic links,
  HMAC-derived master/case IDs, protected decision evidence, and a review queue.
- Optional human `ACCEPT`/`REJECT`/`ABSTAIN` decisions with reviewer provenance,
  timezone validation, conflict rejection, and reversible crosswalk rebuilding.
- One Gold row per accepted Silver admission, using the Phase 3 master identity to
  detect readmission at either hospital from 0 through 30 days after discharge.
- Discharge-time demographic, encounter-history, diagnosis-group, and standardized
  laboratory summary features without names, phone numbers, local patient IDs, birth
  dates, states, lab IDs, or next-admission details.
- Explicit death/no-discharge exclusions and right-censoring statuses, an aggregate
  audit with source hashes, deterministic output, atomic writes, and overwrite
  protection.
- Admission-level readmission rates with Wilson 95% confidence intervals across
  hospital, sex, age, diagnosis, discharge status, utilization, length of stay, year,
  and month.
- Primary and complementary suppression with an explicit minimum cell size, plus
  deterministic aggregate JSON/CSV reports that contain no admission or patient IDs.
- A 13-check release validator covering evidence, package version, Git protections,
  hashes, row/label reconciliation, suppression integrity, identifier exclusion, and
  rule-version continuity.

Model training, patient-level risk scoring, causal inference, and clinical
recommendations remain out of scope.

## Setup

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest --basetemp=work/pytest
```

If package installation is unavailable in an offline environment, tests still run
from the source checkout because `tests/conftest.py` adds `src` to the import path.

## End-to-end run for the official starter files

Place the three files in `data/raw/lakeside_health_network/` using an approved secure
copy process. Never replace an existing delivery in place; archive/version it first.

Create the aggregate-only source profile:

```powershell
patientra-profile data/raw/lakeside_health_network/patients.csv data/raw/lakeside_health_network/admissions.csv data/raw/lakeside_health_network/lab_results.csv --output data/silver/raw_schema_profile.json
```

Ingest each file without altering source values:

```powershell
patientra-ingest data/raw/lakeside_health_network/patients.csv --source-system "Lakeside Health Network"
patientra-ingest data/raw/lakeside_health_network/admissions.csv --source-system "Lakeside Health Network"
patientra-ingest data/raw/lakeside_health_network/lab_results.csv --source-system "Lakeside Health Network"
```

Run Silver with explicit interpretation choices:

```powershell
patientra-silver --patients data/bronze/lakeside_health_network/patients.bronze.csv --admissions data/bronze/lakeside_health_network/admissions.bronze.csv --lab-results data/bronze/lakeside_health_network/lab_results.bronze.csv --slash-date-order dmy --numeric-sex-code 1=M --numeric-sex-code 2=F
```

For this delivery, DMY is supported by 1,879 slash dates whose first component is
greater than 12 and zero whose second component is greater than 12. The numeric sex
mapping is deliberately a command-line codebook rather than a hidden assumption; it
must be confirmed with the data owner before production use. Omitting either choice
causes affected rows to be quarantined rather than guessed.

Use `--overwrite` only for an intentional rerun of derived outputs. It never changes
the files under `data/raw/` or existing Bronze source values.

## Phase 3 identity resolution

Supply a stable 32-character-or-longer secret through the environment or a production
secrets manager. Do not put the secret in command history, source control, or audit
files.

```powershell
$env:PATIENTRA_MATCH_KEY = "retrieve-this-from-your-approved-secret-store"
patientra-match --patients data/silver/patients.silver.csv
```

The local verified run uses a randomly generated key stored only in the Git-ignored
`.env.phase3.local`. Keep the same protected key for reproducible master IDs. See
`docs/human_oversight.md` before applying reviewer decisions. The verified Phase 3
run applied all eight queued reviews: four accepted links and four rejected links,
with no cases left pending.

## Phase 4 Gold feature engineering

Use the official case-study observation end of `2025-12-31`. The command fails if an
admission starts after that cutoff, so later evidence cannot silently influence the
label.

```powershell
patientra-gold --patients data/silver/patients.silver.csv --admissions data/silver/admissions.silver.csv --lab-results data/silver/lab_results.silver.csv --patient-master data/matching/patient_master.csv --observation-end 2025-12-31 --output-dir data/gold
```

Use `--overwrite` only for an intentional rerun. The verified official-file run
produced 2,938 rows: 549 positive, 2,278 negative, and 111 blank labels with explicit
exclusion/censoring statuses. See [docs/gold.md](docs/gold.md) for the complete feature
and label contract.

## Phase 5 readmission analytics

Analyze only valid Phase 4 labels and apply the default minimum cell size of 11:

```powershell
patientra-analytics --gold data/gold/readmission_features.csv --output-dir outputs/phase5 --minimum-cell-size 11
```

The verified run analyzed 2,827 eligible admissions and found 549 readmissions: an
admission-level rate of 19.42% with a Wilson 95% interval of 18.00%–20.92%. Eight of
51 breakdown rows were suppressed. These are descriptive associations, not causal or
clinical conclusions. See [docs/analytics.md](docs/analytics.md).

## Phase 6 validation and presentation

Run the final release gate after Phases 4 and 5:

```powershell
patientra-validate --repository-root . --gold data/gold/readmission_features.csv --gold-audit data/gold/readmission_feature_audit.json --analytics-report outputs/phase5/readmission_analytics.json --analytics-breakdowns outputs/phase5/readmission_breakdowns.csv --analytics-audit outputs/phase5/readmission_analytics_audit.json --output outputs/phase6/release_validation.json
```

The verified run passes all 13 release checks and the complete 31-test suite. The
eight-slide presentation uses aggregate evidence only, with editable native charts
and tables. See [docs/validation.md](docs/validation.md).

## Outputs

| Location | Contents | Patient-level data | Git tracked |
|---|---|---:|---:|
| `data/raw/` | Exact provider delivery | Yes | No |
| `data/bronze/` | Raw cells plus lineage and manifests | Yes | No |
| `data/silver/` | Clean tables, metadata-only profiles, aggregate audit | Yes in CSVs | No |
| `data/matching/` | Patient master, decisions, review queue, aggregate audit | Yes in CSVs | No |
| `data/gold/` | Admission features, label, and aggregate audit | Yes in CSV | No |
| `data/quarantine/` | Rejected source rows plus reason codes and lineage | Yes | No |
| `data/synthetic/` | Clearly synthetic development examples | No real data | Yes |
| `outputs/phase5/` | Suppressed aggregate analytics and audit | No identifiers | No |
| `outputs/phase6/` | Final release validation report | No identifiers | No |

See [docs/silver.md](docs/silver.md) for the full rule contract and
[docs/security.md](docs/security.md) for handling requirements. Aggregate results from
the verified official-file run are in
[docs/phase2-verification.md](docs/phase2-verification.md). The matching contract is in
[docs/matching_strategy.md](docs/matching_strategy.md), and phase evidence is indexed
under [docs/evidence](docs/evidence/README.md).
