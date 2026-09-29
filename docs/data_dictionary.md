# Data dictionary and Bronze contract

No real source schema has been supplied. The clinical columns below are therefore
dataset families to confirm during source onboarding, not asserted field names.

## Expected logical source datasets

| Dataset family | Business grain to confirm | Examples of concepts to confirm |
|---|---|---|
| Patients | One current registration record or one version per local patient | Local patient identifier, demographics, contact fields |
| Admissions | One encounter/admission | Local encounter ID, local patient ID, admit/discharge times, diagnoses |
| Laboratory results | One reported test result/version | Local patient/encounter ID, specimen/result time, test, value, unit |

Both Lakeside General Hospital and Riverside Specialist Hospital may name, encode,
and version these concepts differently. Phase 1 does not force a shared schema.

## PATIENTRA lineage columns

| Column | Type | Definition |
|---|---|---|
| `_source_system` | string | Operator-supplied organization/system label; not inferred |
| `_source_file` | string | Input basename only; excludes workstation directory |
| `_source_row_number` | string integer | Physical CSV record number, with header as row 1 |
| `_source_sha256` | string | Lowercase SHA-256 of exact input bytes |
| `_ingested_at_utc` | ISO-8601 string | One UTC timestamp shared by all rows in the run |
| `_ingestion_run_id` | UUID string | Identifier shared by all rows in the run |

Quarantine adds `_quarantine_reason`, currently one of `too_few_fields` or
`too_many_fields`. Extra fields are not included in the rectangular quarantine CSV;
the original raw file and row lineage remain the authoritative evidence. This avoids
silently widening a schema while ensuring the raw delivery is retained securely.

## Preservation rules

- All source cells are strings. Leading zeros and source representations are retained.
- Empty fields remain empty strings; Phase 1 does not equate them with null.
- Whitespace, capitalization, codes, dates, numeric formatting, and units are not
  normalized.
- CSV syntax is parsed, so escaped quotes and embedded line breaks become their cell
  content, and output quoting/line endings may differ from the source bytes.
- Column order is preserved, followed by PATIENTRA lineage columns.
- Reserved PATIENTRA metadata names in a source header cause a hard failure.

## Schema onboarding questions

For each delivered file, obtain an owner-approved specification covering grain,
primary/business keys, column meanings, types, null conventions, time zone, date
formats, code systems and versions, unit systems, extract window, update/correction
behavior, encoding, delimiter, expected counts, and reconciliation totals.
