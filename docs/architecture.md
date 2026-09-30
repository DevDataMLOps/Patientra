# Bronze, Silver, identity, and Gold architecture

## Purpose

Create a trustworthy landing layer for two hospitals without assuming schemas that
have not been delivered. Bronze preserves evidence; later layers interpret it.

```text
Approved secure transfer
        |
        v
source-specific raw landing zone (read-only operationally)
        |
        | file checks + SHA-256 + CSV structural validation
        v
  +----------------------+       malformed field count
  | Bronze CSV           |------------------------------+
  | source strings       |                              |
  | + row lineage        |                              v
  +----------------------+                    quarantine CSV
        |                                     + reason + lineage
        v
metadata-only manifest
        |
        v
Silver schema contract, cleaning, deduplication, and reason-coded quarantine
        |
        v
governed candidate blocking and one-to-one identity decisions
        |
        +------ uncertain evidence ------> protected human review queue
        |                                      |
        |                         ACCEPT / REJECT / ABSTAIN
        v                                      |
patient_master + decision evidence <-----------+
        |
        v
leakage-controlled Gold features + readmission label
        |
        v
suppressed aggregate readmission analytics
        |
        v
release validation + aggregate stakeholder presentation
        |
        v
future separately governed modeling, if approved
```

## Boundaries and trust

| Zone | Purpose | Contains patient-level data? | Git tracked? |
|---|---|---:|---:|
| `data/raw` | Original provider delivery | Yes, when available | No |
| `data/bronze` | Parsed cells plus lineage | Yes | No |
| `data/silver` | Standardized records plus metadata-only audit/profile | Yes in CSVs | No |
| `data/matching` | Protected crosswalk, decisions, and review queue | Yes | No |
| `data/gold` | Admission features, labels, and aggregate audit | Yes in CSV | No |
| `outputs/phase5` | Suppressed aggregate analytics and audit | No direct identifiers | No |
| `outputs/phase6` | Release validation report | No direct identifiers | No |
| `data/quarantine` | Structurally invalid rows | Yes | No |
| `data/synthetic` | Demonstration and development | No real data | Yes |
| `outputs` | Approved non-sensitive deliverables only | Must not | Empty only |

The local folders are a development convention, not a claim of production-grade
storage. In production, use encrypted storage, source-specific identities, private
networking, audit logs, versioning, retention rules, and a secrets manager.

## Ingestion sequence

1. Resolve and validate the regular `.csv` input file.
2. Validate the source-system identifier and delimiter.
3. Compute a SHA-256 digest of the exact input bytes.
4. Decode as UTF-8 with optional BOM by default and validate the header.
5. Stream rows through the standard CSV parser; no cell transformations occur.
6. Send rows with the expected field count to Bronze.
7. Send rows with a different field count to quarantine with a reason code.
8. Atomically replace temporary outputs only after the stream completes.
9. Write a metadata-only manifest and log counts only.

## Reliability choices

- Streaming avoids loading the whole delivery into memory.
- Atomic same-directory replacement avoids publishing partial CSVs.
- Existing outputs are protected unless overwrite is explicit.
- File hash, row number, UTC time, and run ID support audit and replay.
- Exceptions and logs omit cell values.
- Output permissions are restricted on a best-effort basis; access control must also
  be enforced by the host and production platform.

## Current boundaries

- Header-based sensitive-column detection is advisory and cannot discover all PHI.
- CSV formula payloads remain inert text here but can execute if opened in a
  spreadsheet; do not open hospital exports in desktop spreadsheet software.
- Deterministic output names support a simple starter workflow, not multi-version
  orchestration. Production should key objects by delivery ID and hash.
- Silver checks the documented starter schema, local keys, references, and chronology,
  but does not claim clinical plausibility ranges without an approved clinical rulebook.
- Identity resolution accepts only high-confidence one-to-one links; uncertain links
  require human review and remain separate until accepted.
- Gold labels use the explicit observation cutoff, preserve deaths/no-discharge/right-
  censored rows with blank labels, and do not expose future admission details.
- Phase 5 analyzes valid labels only, publishes confidence intervals, and applies
  primary plus complementary suppression to small breakdown cells.
- Phase 6 independently reconciles evidence, hashes, rows, labels, breakdowns,
  suppression, identifiers, and rule versions before presentation.
- Model training, patient-level risk scoring, causal inference, and clinical
  recommendations remain out of scope.
