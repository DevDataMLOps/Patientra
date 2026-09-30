## Summary

Describe the problem, the proposed change, and the affected pipeline phase.

## Verification

- [ ] `python -m pytest -q` passes.
- [ ] `python -m compileall -q src tests` passes.
- [ ] New or changed behavior has reproducible tests.
- [ ] Documentation and evidence contracts are updated where needed.

## Data protection

- [ ] No raw, Bronze, Silver, matching, Gold, quarantine, or patient-level output is included.
- [ ] Logs, fixtures, screenshots, and examples contain synthetic or approved aggregate data only.
- [ ] No secret, HMAC key, credential, local path, or reviewer identity is committed.
- [ ] Suppression and identifier-exclusion controls remain intact.

## Release impact

- [ ] Rule or schema versions were updated if semantics changed.
- [ ] Backward compatibility and rerun behavior were considered.
- [ ] The Phase 6 release gate was run when derived-output contracts changed.
