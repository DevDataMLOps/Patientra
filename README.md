# PATIENTRA — Phase 1 data foundation

Starter repository for the Lakeside Health Network readmission data engineering
challenge. Phase 1 creates a reproducible, privacy-conscious Bronze ingestion layer
before any real hospital files are available.

> **Data status:** This repository contains synthetic examples only. It contains no
> real patient data and makes no findings about either hospital, readmissions, data
> quality, or model performance.

## What Phase 1 delivers

- Generic CSV ingestion that preserves source cells as strings; it does not parse,
  normalize, impute, deduplicate, or match records.
- Lineage on every accepted and quarantined row: source system, source file, source
  row number, file SHA-256, UTC ingestion time, and run ID.
- Structural checks for an empty/invalid header, duplicate columns, reserved metadata
  names, malformed CSV, unexpected field counts, file type, encoding, and delimiter.
- Local quarantine of rows with too many or too few fields, with a reason code.
- Atomic output writes, overwrite protection, metadata-only logs/manifests, and
  best-effort restrictive output permissions.
- Explicitly synthetic fixtures and automated tests.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pytest
```

Try the synthetic file:

```bash
patientra-ingest data/synthetic/lakeside/patients.csv \
  --source-system "Lakeside General Hospital"
```

On PowerShell, run the command on one line or replace `\` with PowerShell's line
continuation character. Successful runs create a Bronze CSV and JSON manifest under
`data/bronze/<source>/`. Structurally invalid rows go to
`data/quarantine/<source>/`. These paths are ignored by Git.

To ingest a semicolon-delimited export or a known alternate encoding:

```bash
patientra-ingest path/to/file.csv --source-system "Riverside Specialist Hospital" \
  --delimiter ";" --encoding "utf-8-sig"
```

The supported delimiter choices are comma, semicolon, tab, and pipe. The default
encoding is UTF-8 with optional byte-order mark. Specify a different known encoding
only when confirmed by the data provider.

## Expected source families

The challenge describes `patients`, `admissions`, and `laboratory_results` from
Lakeside General Hospital and Riverside Specialist Hospital. Their real schemas are
not yet known, so Phase 1 intentionally imposes no invented clinical columns. Place
received files in the matching `data/raw/` source folder only after following the
secure handling checklist in [docs/security.md](docs/security.md).

## Repository map

```text
patientra/
├── data/
│   ├── raw/{lakeside,riverside}/  # secure landing zones; contents ignored
│   ├── bronze/                    # immutable-form row copies + lineage; ignored
│   ├── quarantine/                # structurally invalid rows; ignored
│   └── synthetic/                 # clearly fake examples only
├── docs/                          # architecture, contracts, security, roadmap
├── outputs/                       # non-sensitive published artifacts only
├── sql/{bronze,silver,gold}/      # future layer-specific SQL
├── src/patientra/                 # application package
└── tests/                         # pytest suite and synthetic fixtures
```

## Bronze contract

Bronze is a faithful, auditable landing layer. Source values such as `000123`,
`03/04/26`, or `mg/dL` remain exactly as represented by Python's CSV parser. CSV
quoting and line endings may be normalized in the output serialization, but cell
content is not transformed. A SHA-256 digest identifies the exact input bytes.

Each logical source file maps to one deterministic destination. Existing results are
not overwritten unless `--overwrite` is explicitly supplied. Repeated deliveries
should be archived or renamed according to an agreed source-file convention before
production use; a production object store should add versioning and retention locks.

## What is deliberately out of scope

Phase 1 does not infer date formats, standardize sex or diagnosis values, convert lab
units, deduplicate admissions, link patients, label readmissions, build features, or
train/evaluate AI. Those steps require real schemas, clinical governance, and
documented decisions. See [docs/phase2-readiness.md](docs/phase2-readiness.md).

## Safety rule

Never commit real raw, Bronze, quarantine, manifest, secret, or ad-hoc output files.
Column-name detection is only a warning aid and is not de-identification. Treat every
hospital export as sensitive even if obvious identifiers appear absent.
