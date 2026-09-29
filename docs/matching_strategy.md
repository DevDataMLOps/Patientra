# Patient matching strategy placeholder

Patient matching is intentionally not implemented in Phase 1. A false merge can attach
the wrong clinical history to a person, while a missed match can hide a readmission.
The Phase 2 design must be approved before any identifiers are compared.

At minimum, the design must separate candidate generation from match scoring, prefer
multiple corroborating identifiers, measure errors by hospital and population group,
automatically accept only a documented high-confidence band, reject a low-confidence
band, and route the uncertain band to trained human review. Every decision needs
evidence, model/rule version, reviewer provenance where applicable, and reversibility.

Never place direct identifiers in logs or feature tables. Hashing alone is not an
adequate identity or privacy strategy; use an access-controlled crosswalk and an
approved keyed transformation where appropriate.
