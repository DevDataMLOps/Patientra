# PATIENTRA — Clean Data Before Smart Care

**One Patient. One Care.**

Two hospitals. One connected patient identity. A more trustworthy foundation for healthcare intelligence. The complementary tagline expresses a human-centered ambition for continuity, grounded in governed identity resolution; it does not mean PATIENTRA delivers or guarantees clinical care.

## 1. The Invisible Patient

A hospital can record every encounter and still miss part of a patient's journey. When a person returns through another hospital's doors, a new local identifier can make a connected story look like two unrelated visits. The encounter is visible. The connection is missing.

> **Illustrative patient journey — invented, not a repository record.** Imagine a person discharged from one hospital who needs admission at another two weeks later. Each hospital knows its own visit. A local-ID-only report may miss the return. PATIENTRA compares corroborating identity evidence; if that evidence conflicts, an authorized reviewer can accept, reject, or abstain. Only a governed link allows the two encounters to contribute to one network history. This example illustrates the workflow, not a demonstrated clinical outcome or an actual patient's experience.

PATIENTRA begins with that missing connection. Before healthcare teams can trust an intelligent system, they need to trust the data that tells them who returned, when, and how the conclusion was reached.

## 2. The Challenge

The fictional Lakeside Health Network case study brings hospital CSV deliveries together, but combining files is only the beginning. Dates and coded values need explicit interpretation. Laboratory units must agree. Duplicate or invalid records need accountable handling. Local patient registrations need conservative linkage. A missing follow-up window must never become evidence that no readmission occurred.

The engineering challenge is to turn fragmented records into defensible network-level answers without concealing uncertainty or exposing patient-level information. A mistaken identity merge can attach someone else's history to a person; an unexplained cleaning rule can change a denominator. Both threaten trust.

The repository's [architecture](architecture.md) and [Silver contract](silver.md) make those risks concrete. The case study is synthetic; its records are nevertheless handled as sensitive health data.

## 3. Introducing PATIENTRA

**PATIENTRA turns fragmented hospital data into auditable, disclosure-controlled readmission intelligence.** Its promise is captured in the title: clean data before smart care.

The solution preserves source evidence, standardizes through explicit rules, resolves identities with human oversight, builds governed admission-level features and labels, and releases aggregate analytics through an independent validation gate. Its [Core MVP](core_mvp.md) answers three focused questions: what identity matching changes in the readmission rate, which released diagnosis group has the highest rate, and how much matching work requires human review.

This is a working data engineering and descriptive analytics foundation. It does not deliver clinical predictions or recommend treatment.

## 4. Engineering the Solution

Each stage earns the right to pass data to the next. The [phase evidence index](evidence/README.md) links the acceptance boundaries and recorded results.

| Stage | What happens | Why it matters |
|---|---|---|
| **Bronze: preserve the evidence** | Preserve source values with hashes and lineage; quarantine malformed structures. | A published answer can be traced back to a delivery rather than an overwritten spreadsheet. See [Bronze evidence](evidence/phase-1-bronze/README.md). |
| **Silver: make meaning explicit** | Standardize dates, codes, and lab units; validate keys, references, and chronology; deduplicate and quarantine with reasons. Ambiguous formats require operator-supplied rules. | Cleaning decisions remain visible and every source row is reconciled. See [Silver evidence](evidence/phase-2-silver/README.md). |
| **Identity matching and human review** | Generate controlled cross-hospital candidates. Automatically link only uniquely corroborated, one-to-one pairs; send plausible conflicts to protected review. Keep a reversible crosswalk and decision provenance. | A shared phone alone is insufficient. Uncertainty cannot silently become a merged identity. See [matching strategy](matching_strategy.md) and [human oversight](human_oversight.md). |
| **Gold: construct the analytical record** | Create one row per accepted admission. Use the master identity for an inclusive 0–30-day readmission label and an explicit observation cutoff. Keep death, missing discharge, and incomplete follow-up distinct from negatives. | The denominator and outcome have a documented meaning. Prior history uses completed stays available by admission; index-stay labs and encounter features describe the stay at discharge. Future-admission details are excluded from predictors. See [Gold contract](gold.md). |
| **Analytics: publish defensible aggregates** | Calculate admission-level rates and Wilson 95% intervals; suppress small cells and add complementary suppression where required. | Useful summaries do not require publishing patient histories. Associations remain descriptive and unadjusted. See [analytics methodology](analytics.md). |
| **Validation: stop an unsafe release** | Independently check schemas, hashes, counts, lineage, suppression, identifiers, and rule-version continuity. Fail the release when a check fails. | Evidence integrity is a release condition. The gate is not clinical validation or a formal privacy determination. See [validation contract](validation.md). |

## 5. What PATIENTRA Revealed

The strongest result is a measurable change in visibility. The checked-in [aggregate Core MVP report](evidence/judge-results/patientra_core_mvp.json) actually calculates the comparison; these are not inferred before-and-after rates.

| Same eligible cohort: 2,827 admissions | Positive admissions | Readmission rate |
|---|---:|---:|
| Before identity matching: hospital-local identity | 506 | 17.90% |
| After identity matching: governed master identity | 549 | 19.42% |

**43 admission-level readmissions were hidden by local IDs**, a **1.52 percentage-point increase** in the measured rate. Both calculations use the same cohort, inclusive 0–30-day rule, and observation end of **2025-12-31**. No local-ID positive became negative after matching. The [judge-results derivation](evidence/judge-results/README.md) explains the comparison.

**Cross-hospital positives and truly hidden readmissions are different measures.** The [Gold evidence](evidence/phase-4-gold-features/README.md) records **44 cross-hospital positive events**. That count describes cross-hospital outcome evidence; it does not establish that all 44 were missed locally. The fixed-cohort comparison establishes **43 newly positive admissions**. A cross-hospital positive can already have a qualifying local return, so the two counts must not be substituted for one another.

Other verified findings show what supports that result:

- [Silver evidence](evidence/phase-2-silver/README.md) reconciles **3,056 source admissions into 2,938 retained and 118 quarantined**, and **11,330 lab results into 10,231 retained and 1,099 quarantined**. Quarantine is accountable handling, not silent deletion.
- [Identity evidence](evidence/phase-3-identity-resolution/README.md) records **304 automatic pairs** and **8 reviewed pairs: 4 accepted, 4 rejected**, yielding **1,996 master identities from 2,304 registrations**. Eight is review workload, not eight accepted links.
- [Gold evidence](evidence/phase-4-gold-features/README.md) reconciles **2,938 admission rows** into **549 positives, 2,278 negatives, and 111 unlabeled rows**. Those 111 comprise **58 deaths, 30 missing discharges, and 23 incomplete follow-up windows**.
- The [Core MVP report](evidence/judge-results/patientra_core_mvp.json) identifies **I50 at 32.13%: 133 positives among 414 eligible admissions**, the highest rate among released, unsuppressed diagnosis groups. This is a group-level description, not an individual risk score or evidence of a cause.
- [Analytics evidence](evidence/phase-5-readmission-analytics/README.md) reports the overall **19.42% rate with a Wilson 95% interval of 18.00%–20.92%** and **8 suppressed rows out of 51 breakdown rows**. [Release evidence](evidence/phase-6-validation-presentation/README.md) records **13 of 13 checks passed**.

These are recorded synthetic-case-study results. They demonstrate pipeline behavior, not real-world matching accuracy, improved care, preventable admissions, or generalizability. Rates count admissions rather than unique people, and descriptive differences may reflect case mix, repeated admissions, confounding, or chance.

## 6. Humans Remain in Control

PATIENTRA makes uncertainty a decision point. Reviewers can **ACCEPT, REJECT, or ABSTAIN**; missing decisions remain pending, and abstention does not create a link. Reviewer identity and a timezone-aware timestamp are mandatory. Accepted decisions must preserve one-to-one constraints. Corrections can rebuild the crosswalk without overwriting source records. The [human review protocol](human_oversight.md) documents both implemented controls and governance expectations such as sampling, escalation, and rule approval.

Privacy is part of this control model. Source records, review cases, crosswalks, and Gold rows remain protected and Git-ignored. Published evidence is aggregate-only. Pseudonymous tokens remain sensitive, and suppression reduces disclosure risk without proving de-identification. This storyline links reviewed aggregate evidence and contracts; it reproduces no patient-level data. See the [security guidance](security.md) and [repository security policy](../SECURITY.md).

## 7. Business Impact

For a hospital network, an incomplete rate can frame the wrong operational question. In this case study, governed identity resolution changes the measured picture from 17.90% to 19.42%. **The higher rate represents better visibility, not worsening care caused by PATIENTRA.**

The demonstrated business value is a traceable measurement foundation: leaders can inspect the cohort definition, analysts can explain changes, data owners can investigate quarantine reasons, and review teams can see the documented split between automatic and human work. Released diagnosis summaries can help frame questions for further investigation without prescribing a clinical response.

Potential benefits include better-informed service planning, less manual reconciliation, and more focused quality-improvement inquiry. The repository does **not** measure financial savings, staff time saved, reduced readmissions, improved outcomes, or return on investment. Those benefits require a governed real-world pilot with explicit baselines and evaluation measures.

## 8. The Future

The next step is to test whether this foundation remains trustworthy beyond the synthetic case study: validate source mappings with data owners, assess linkage against an approved reference set, examine subgroup errors, and evaluate workflow usefulness with authorized teams. Secure deployment, interoperable hospital integrations, dashboards, and APIs are possible extensions rather than demonstrated production capabilities.

**No clinically validated risk model exists in PATIENTRA.** The current pipeline trains no model and produces no patient-level risk score. Any future modeling would need a separately approved protocol, prediction-time feature definitions, temporal validation, leakage review, calibration, subgroup evaluation, external validation, and clinical governance before use. Discharge-time features must not be presented as information available at admission.

The ambition is to build on evidence deliberately: validate the data foundation, evaluate the workflow, and only then establish whether prediction or intervention adds value.

## 9. Alignment with UN SDGs

PATIENTRA aligns with several of the **United Nations Sustainable Development Goals (SDGs)** through its intended approach to trustworthy health information. These are **potential contributions**, not proven SDG outcomes, measured indicator improvements, or UN endorsement.

| Goal | Intended or potential contribution | Evidence still needed |
|---|---|---|
| [**SDG 3 — Good Health and Well-Being**](https://sdgs.un.org/goals/goal3) | More complete network-level histories and auditable readmission measurement could support investigation and planning for continuity and quality of care. | A real-world evaluation must establish whether use improves services or health outcomes. No clinical benefit is demonstrated here. |
| [**SDG 10 — Reduced Inequalities**](https://sdgs.un.org/goals/goal10) | Making fragmented journeys visible could help teams investigate whether some groups are systematically missed by data processes. | Representative data, subgroup linkage-error analysis, and equity-focused evaluation are required. The project does not demonstrate reduced inequality or certified fairness. |
| [**SDG 17 — Partnerships for the Goals**](https://sdgs.un.org/goals/goal17) | Shared contracts, traceable evidence, and protected human review provide a pattern for accountable cooperation among hospitals, data teams, and governance partners. | Formal data-sharing agreements and evaluation of actual partnerships are needed. The case study does not establish deployed institutional collaboration. |

The illustrative patient at the beginning did not need a more impressive dashboard. Their journey needed a trustworthy connection. PATIENTRA demonstrates how to build that connection carefully, account for uncertainty, and show the evidence behind the answer.

**Clean data before smart care: make the journey visible, keep people in control, and earn the next decision with evidence.**

**One Patient. One Care.** A human-centered ambition, supported by trustworthy data and accountable identity links.
