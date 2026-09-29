# Phase 1 architecture

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
future Silver cleaning, matching, and governed human review
        |
        v
future Gold admission features and 30-day readmission labels
```

## Boundaries and trust

| Zone | Purpose | Contains patient-level data? | Git tracked? |
|---|---|---:|---:|
| `data/raw` | Original provider delivery | Yes, when available | No |
| `data/bronze` | Parsed cells plus lineage | Yes | No |
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

## Known Phase 1 limitations

- Header-based sensitive-column detection is advisory and cannot discover all PHI.
- CSV formula payloads remain inert text here but can execute if opened in a
  spreadsheet; do not open hospital exports in desktop spreadsheet software.
- Deterministic output names support a simple starter workflow, not multi-version
  orchestration. Production should key objects by delivery ID and hash.
- Phase 1 checks structure, not clinical validity or cross-file referential integrity.
