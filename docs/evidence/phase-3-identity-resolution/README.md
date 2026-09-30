# Phase 3 evidence — Patient identity resolution

## Objective and acceptance boundary

Link only high-confidence, one-to-one cross-hospital identities; retain every local
ID in a protected reversible crosswalk; and route conflicting but plausible candidates
to humans. No uncertain candidate may be merged without an explicit accepted review.

## Verified official-file run

| Measure | Result |
|---|---:|
| Silver patient registrations | 2,304 |
| LG / RS registrations | 1,425 / 879 |
| Controlled candidate pairs | 713 |
| High-confidence automatic pairs | 304 |
| Automatic one-to-many conflicts | 0 |
| Human-reviewed pairs | 8 |
| Human-accepted / rejected pairs | 4 / 4 |
| Patient-master crosswalk rows | 2,304 |
| Unique master patients | 1,996 |
| Source rows linked automatically or by accepted review | 616 |
| Source rows pending review | 0 |

Automatic rule counts were 288 `UNIQUE_PHONE_DOB_LAST` and 16
`UNIQUE_PHONE_FULL_NAME`. All eight review cases use
`EXACT_FULL_NAME_WITH_BIRTH_COMPONENT`: exact normalized full name, sex, and state,
but a conflicting full birth date with only the birth year or month/day agreeing.
All eight cases were reviewed using the protected decision contract. Four accepted
pairs were linked and four rejected pairs remain separate master identities.

## Verification evidence

- The current complete suite passes 31 tests.
- Master/case IDs are deterministic HMAC tokens when the same protected key is used.
- Every accepted automatic link is one-to-one and every local ID appears once in the
  crosswalk.
- All eight human decisions include reviewer provenance, a timezone-aware UTC
  timestamp, and a non-sensitive review note.
- The protected queue contains local IDs and evidence categories but no duplicated
  names, phones, or birth dates.
- The aggregate audit contains none of the tested identifiers or demographic values.
- The key is absent from audit output and Git; only a short key fingerprint is stored.
- Raw, Bronze, Silver, and review-decision inputs were not overwritten; matching
  outputs were reproducibly rebuilt from those inputs.

## Human review outcome

The eight queued cases received four `ACCEPT` and four `REJECT` decisions. No case is
pending or abstained. Reviewer metadata and case-level evidence remain only in the
protected, Git-ignored operational files.

## Next gate

Phase 4 may use the accepted master crosswalk. Rejected pairs remain separate. Phase 4
must define the readmission cohort, death/transfer behavior, time boundaries, and
leakage controls before producing labels.
