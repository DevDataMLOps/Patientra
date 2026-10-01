# Phase 7 evidence — Data serving and snapshot observability

## Objective and acceptance boundary

Record the successful local publication and querying of a disclosure-controlled
SQLite snapshot after Phase 6 validation. Phase 7 is an aggregate-only, locally
verified serving system. It is not a publicly deployed API or a production clinical
service. The database was created locally at
`outputs/phase7/patientra_serving.sqlite` and must remain outside Git and GitHub
artifacts.

## Execution results and evidence provenance

The operator supplied the following verified observations from the reconstructed
local execution. They describe that execution, not the historical human-reviewed
release documented in Phases 1–6.

| Metric | Verified result reported by operator |
|---|---:|
| Phase 7 SQLite publication | Successful |
| Phase 6 validation checks | 13 passed |
| Gold admission records | 2,938 |
| Eligible admissions | 2,827 |
| Excluded admissions | 111 |
| 30-day readmissions | 548 |
| Provisional readmission rate | 19.38% |
| Analytics breakdown rows | 51 |
| Suppressed breakdown rows | 8 |
| Unique master patients | 2,000 |
| Unresolved human-review cases | 8 |
| SQLite release status | PASS |
| Snapshot freshness at execution | FRESH |

During documentation review, available local historical Phase 5 analytics and
Phase 6 validation outputs corroborated 2,938 Gold rows, 2,827 eligible rows,
111 excluded rows, 51 breakdown rows, 8 suppressed rows, and 13 passing checks.
Those artifacts contain **549**, rather than 548, readmissions and cannot serve as
direct verification of the reconstructed snapshot. The reported provisional rate
is arithmetically consistent: `548 / 2,827 × 100 = 19.38%` when rounded.

The reconstructed database and its associated audits were not available in the
documentation review workspace. Its publication, query results, 548 readmissions,
2,000 unique master patients, 8 unresolved reviews, and publication-time `FRESH`
status therefore remain operator-attested, rather than independently reverified
here. No execution timestamp, checksum, screenshot, or database export is supplied
as evidence for that run.

## Architecture and serving responsibilities

```mermaid
flowchart LR
    B[Bronze] --> S[Silver]
    S --> I[Identity Resolution]
    I --> G[Gold]
    G --> A[Analytics]
    A --> V[Phase 6 Validation]
    V --> Q[Phase 7 SQLite Serving]
```

Bronze preserves delivery lineage; Silver applies explicit cleaning and quarantine
rules; identity resolution builds governed master identities with human oversight;
Gold constructs admission features and 30-day labels; analytics aggregates and
suppresses protected cells. Phase 6 validates the release before Phase 7 publishes
the approved aggregate inputs.

| SQLite object | Responsibility |
|---|---|
| `overall` table | Aggregate admission-level readmission counts, rate, and confidence intervals. |
| `breakdowns` table | Analytics rows with suppression markers and nullified protected metrics. |
| `released_breakdowns` view | Queryable unsuppressed aggregates, filtered by an empty suppression reason. |
| `pipeline_status` table | Validation status, snapshot freshness, row reconciliation, publication/run metadata, and artifact hashes. |

The publisher checks all 13 passing release checks, input hashes, analytics rule
version and schema, approved breakdown dimensions, cohort and breakdown counts,
CSV/JSON agreement, and suppression integrity. Released cells require a minimum
size of 11; suppressed metrics must be NULL. Publication uses a temporary database
and atomic replacement, with explicit overwrite required for an existing snapshot.
See the [Phase 7 implementation contract](../../phase7-serving.md).

## Successful local SQLite queries

The operator reported successful queries of `overall` and `pipeline_status`.
The following projections show only the aggregate results and safe status fields
needed to reproduce that inspection locally:

```sql
SELECT eligible_admissions, readmitted_admissions, readmission_rate_pct
FROM overall;

SELECT release_status, freshness_status, validation_checks_passed,
       gold_rows, eligible_rows, excluded_rows, breakdown_rows, suppressed_rows
FROM pipeline_status;
```

The reported `overall` result was 2,827 eligible admissions, 548 readmissions,
and 19.38%. The reported `pipeline_status` result was `PASS`, `FRESH`, 13 passing
checks, 2,938 Gold rows, 2,827 eligible rows, 111 excluded rows, 51 breakdown rows,
and 8 suppressed rows. These are the supplied observations, not a new query
transcript generated during documentation review.

## Identity governance and interpretation limitations

**Eight patient identity-review cases remain unresolved.**

The reconstructed release contains 548 observed 30-day readmissions, compared with
549 in the historical human-reviewed release. Its 19.38% provisional rate and
2,000 unique master patients must not be represented as identical to the historical
19.42% rate and 1,996 master patients. The historical release applied eight review
decisions (four accepted and four rejected); this reconstructed run retains an
unresolved governance limitation. Earlier evidence remains a record of that
separate historical release.

`PASS` validates the implemented technical release checks. It does not establish
clinical accuracy or complete patient identity resolution. Identity decisions and
their downstream effects require governed review before claiming equivalence with
the historical release.

`FRESH` refers to analytics-run recency at publication, using a 24-hour threshold.
It does not describe the freshness of the underlying hospital records and is not
a claim that the saved snapshot remains fresh today.

The results are descriptive synthetic-case-study aggregates. Local publication
does not establish clinical suitability, regulatory compliance, production
readiness, public deployment, continuous monitoring, or alerting.

## Documentation validation and privacy evidence

- Existing automated suite: **39 passed**, using synthetic fixtures.
- `python -m compileall -q src tests`: passed.
- Serving tests cover aggregate publication, suppression, hash-tampering rejection,
  preservation of an existing snapshot after rejection, explicit overwrite, and
  failure when release evidence is missing. These tests verify implementation
  behavior; they do not independently prove the reported reconstructed run.
- Documentation includes only approved aggregate results and control descriptions.
  No raw datasets, patient-level Bronze/Silver/Gold CSVs, identity crosswalks,
  review queues, matching secrets, internal identifiers, or SQLite database are
  included.

## Remaining evidence and release gates

Independent verification of this particular reconstructed run requires local,
read-only comparison of its database against its Phase 5 and Phase 6 audits.
Keep those artifacts protected; any future evidence update should publish only
approved aggregate observations and safe metadata. Resolve the eight identity
reviews and rerun downstream validation before asserting a human-reviewed result.
Public API or dashboard deployment requires a separate approved serving and
disclosure review; no such deployment is claimed here.

## Subsequent independent reconstruction

The Phase 8 hosting follow-up rebuilt an isolated local reconstruction from the
protected Silver inputs without applying historical human-review decisions.
Identity, Gold, analytics, Phase 6 validation, and Phase 7 publication succeeded.
It directly corroborated 2,000 master patients, eight pending reviews, 2,938 Gold
rows, 2,827 eligible admissions, 111 excluded admissions, 548 readmissions, 19.38%,
51 breakdown rows, eight suppressed rows, 13 passing checks, and a fresh publication.

These are verified results of the **new reconstruction**, not a retroactive
verification of the original operator-run database. Earlier provenance limitations
still apply to that original artifact. Historical results remain separate, and
**eight reviews remain unresolved**. See the [Phase 8 follow-up](../phase-8-fastapi/README.md).
