# Sensitive-data handling checklist

This project is designed for health data, but source code alone cannot make a local
workstation or cloud account compliant. Confirm organizational policy, applicable law,
and approval from the data owner/security team before receiving real data.

## Before receipt

- Approve the minimum-necessary fields and documented purpose.
- Establish a secure transfer channel; do not use personal email or consumer sharing.
- Define authorized identities, retention/deletion dates, breach response, and audit
  ownership.
- Provision encrypted, access-controlled raw, Bronze, and quarantine storage.
- Keep production data out of developer laptops unless explicitly authorized.

## During processing

- Treat local patient IDs, quasi-identifiers, and free text as sensitive.
- Never include cell values in logs, issue trackers, screenshots, demos, or prompts.
- Do not open raw CSVs in spreadsheet software; formula-like cells can be dangerous.
- Run malware/content checks required by the organization before ingestion.
- Use secrets management rather than `.env` for production credentials.
- Restrict exports and validate that temporary files inherit secure directory controls.

## Sharing and publishing

- Do not assume hashing identifiers de-identifies a dataset.
- Require disclosure review for aggregates, small cells, examples, and screenshots.
- Publish only synthetic or formally approved de-identified artifacts.
- Rotate/revoke access and execute verified deletion when retention ends.

The code reports only the **count** of possible sensitive column names as an advisory
signal; it does not copy header values into the manifest. It never logs source cell
values. Detection is incomplete by design and must not be used as a gate that declares
data safe.
