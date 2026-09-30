# Phase 6 evidence — Validation and presentation

## Objective and acceptance boundary

Independently validate the Phase 1–5 evidence chain and produce a stakeholder-ready
presentation using aggregate, disclosure-controlled findings only. Phase 6 must not
publish protected source, identity, Gold, or suppressed values.

## Verified release gate

`phase6-validation-v1` returned `PASS` with all 13 checks successful.

| Reconciliation measure | Result |
|---|---:|
| Gold rows | 2,938 |
| Eligible / excluded rows | 2,827 / 111 |
| Analytics breakdown rows | 51 |
| Suppressed breakdown rows | 8 |
| Actual identifier hits in analytics outputs | 0 |
| Complete automated test suite | 34 passed |

The release validation report SHA-256 is
`fa72a5b62cedc1e60d6a82101d7ad217445d5cb13efe5bc32f094266c82f12e0`.
It independently verified these upstream hashes:

- Gold CSV: `0560061b8e62443b2be215786329267ec6edbd74288b74e8337b9aae714faecb`
- analytics JSON: `04d72cb00b774a2dcba7297e6c982829e418aaab56a6402ef220c949ba49ea09`
- analytics CSV: `4627b3c07d44941e8516e32d5cf12afce667c79786579f02923042dc997d2120`

## Presentation verification

The final PowerPoint contains eight slides, three editable native charts, and three
editable native tables. The presentation finalizer verified:

- package integrity: pass, zero findings;
- slide count and 16:9 geometry: pass;
- layout: zero findings and zero warnings;
- Arial font policy: pass;
- native chart workbook references and values: pass for all three charts;
- native table presence: pass for slides 2, 4, and 7; and
- first-party re-import: pass with all eight slides.

All eight final slides were rendered and visually inspected. The final deck SHA-256
is `ac7018f41b81eecbd6e95329512c062038dd9afbf9bfc400448509113fe4f473`.
The deck was not opened in native Microsoft PowerPoint, so native-application behavior
is not claimed beyond the structural, re-import, and rendered-preview checks.

## Scope boundary

Phase 6 validates repository evidence, output integrity, reconciliation, disclosure
controls, and presentation construction. It does not validate clinical suitability,
causality, model performance, fairness, accessibility, or production compliance.
