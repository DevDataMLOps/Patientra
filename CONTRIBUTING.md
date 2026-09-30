# Contributing to PATIENTRA

Thank you for helping improve PATIENTRA. Contributions must preserve the project's
fail-closed behavior, reproducibility, and patient-data boundaries.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q --basetemp work/pytest
```

Use `source .venv/bin/activate` on macOS or Linux.

## Before opening a pull request

1. Create a focused branch and keep the change limited to one clear concern.
2. Add or update synthetic tests for every behavior change.
3. Run the complete test suite and source compilation.
4. Update the relevant rule contract, data dictionary, and phase evidence.
5. Explain any schema, rule-version, rerun, or compatibility impact.
6. Complete every applicable item in the pull-request template.

## Data and privacy rules

Never commit or paste:

- raw, Bronze, Silver, matching, Gold, quarantine, or patient-level output files;
- names, local patient IDs, phones, dates of birth, addresses, review cases, or tokens;
- real or realistic patient rows in fixtures, logs, issues, screenshots, or examples;
- `.env` files, HMAC keys, credentials, private URLs, or workstation-specific secrets; or
- unsuppressed small-cell analytics.

Tests must use clearly synthetic fixtures. Aggregate evidence must pass disclosure review
and must not make hidden cells derivable from totals.

## Engineering expectations

- Prefer standard-library implementations unless a dependency has a clear, documented
  benefit.
- Fail closed on schema drift, ambiguous parsing, or broken lineage.
- Preserve raw and Bronze immutability.
- Keep outputs deterministic when run metadata is fixed.
- Use atomic writes and explicit overwrite flags for derived artifacts.
- Never log cell values or include identifiers in exception messages.
- Treat a rule change as a versioned data-contract change, not an invisible refactor.

## Commit and review quality

Use concise, imperative commit messages such as `Add release hash verification`. Pull
requests should explain the purpose, verification evidence, privacy impact, and rollback
or rerun considerations. Reviewers should be able to reproduce the claim from the
repository without access to protected data.
