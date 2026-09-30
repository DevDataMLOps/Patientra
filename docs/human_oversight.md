# Human review workflow

## Reviewer input contract

Export the protected `review_queue.csv` only to an approved review tool. Reviewers
must use minimum necessary source evidence and return a CSV with exactly:

```text
review_case_id,decision,reviewer_id,reviewed_at_utc,review_notes
```

`decision` is `ACCEPT`, `REJECT`, or `ABSTAIN`. Reviewer identity and a timezone-aware
ISO timestamp are mandatory. Notes are optional and must not copy unnecessary patient
details.

Apply completed decisions with the same matching secret:

```powershell
patientra-match --patients data/silver/patients.silver.csv --review-decisions secure/review_decisions.csv --overwrite
```

The runner rejects unknown/duplicate cases, malformed decisions, missing provenance,
naive timestamps, and accepted decisions that violate the one-to-one constraint.
`ABSTAIN` remains unresolved and requires escalation. Missing decisions remain
`PENDING`; neither status creates a link.

## Governance expectations

- Authenticate reviewers and enforce least privilege.
- Train reviewers on false-merge harm and written decision criteria.
- Permit abstention and escalation; do not force uncertain decisions.
- Use dual review for policy-defined high-risk cases.
- Sample accepted automatic and human decisions for quality assurance.
- Track disagreement, reversal, and false-merge rates by source and relevant groups.
- Version and approve all threshold/rule changes; never tune from production outcomes
  without leakage and fairness review.
- Preserve the prior crosswalk and decision file so a correction is reversible.

The aggregate audit contains counts and rule names only. Local IDs and reviewer data
remain in protected, Git-ignored operational CSVs.
