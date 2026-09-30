# PATIENTRA — Trusted data and patient identity foundation

Reproducible, privacy-conscious data preparation for the fictional Lakeside Health
Network readmission challenge. Phase 1 preserves the provider delivery in Bronze;
Phase 2 profiles and cleans the official `patients`, `admissions`, and `lab_results`
schemas into governed Silver tables with reason-coded quarantine. Phase 3 creates a
conservative cross-hospital `patient_master` and protected human review queue.

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

Readmission labeling, Gold features, outcome rates, and diagnosis analysis remain
out of scope until later phases.

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

## Outputs

| Location | Contents | Patient-level data | Git tracked |
|---|---|---:|---:|
| `data/raw/` | Exact provider delivery | Yes | No |
| `data/bronze/` | Raw cells plus lineage and manifests | Yes | No |
| `data/silver/` | Clean tables, metadata-only profiles, aggregate audit | Yes in CSVs | No |
| `data/matching/` | Patient master, decisions, review queue, aggregate audit | Yes in CSVs | No |
| `data/quarantine/` | Rejected source rows plus reason codes and lineage | Yes | No |
| `data/synthetic/` | Clearly synthetic development examples | No real data | Yes |

See [docs/silver.md](docs/silver.md) for the full rule contract and
[docs/security.md](docs/security.md) for handling requirements. Aggregate results from
the verified official-file run are in
[docs/phase2-verification.md](docs/phase2-verification.md). The matching contract is in
[docs/matching_strategy.md](docs/matching_strategy.md), and phase evidence is indexed
under [docs/evidence](docs/evidence/README.md).
