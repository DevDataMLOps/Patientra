# PATIENTRA maintenance and production authority

DevDataMLOps is the sole accountable maintainer and repository owner. Final
architecture, protected-branch merges, release approval, canonical Databricks
execution, and Phase 10 ownership belong to DevDataMLOps.

Somto-Afudoh contributes with Write access: development branches, notebooks,
pull requests, reviews, and implementation support. somtee-tech currently has
Read access and can contribute through forks and pull requests. Neither account
has administrative or branch-protection authority.

The active default-branch ruleset restricts updates to repository admins, permits
admin bypass only through PRs, requires PRs, and blocks force pushes/deletion.
The maintainer reviews and validates each final diff before merging. CODEOWNERS
requests maintainer review; merge authority is enforced by the ruleset. Formal
required approvals and CI checks must be configured separately if desired.

The release and Databricks workflows accept only DevDataMLOps dispatches on main,
including reruns. They test the checked-out commit before publishing/deploying.
Keep GitHub environments databricks-dev and databricks-prod restricted to main;
only the maintainer administers their deployment credentials.

GitHub Write access inherently permits managing GitHub release objects. An
owner-gated workflow controls the official release process but cannot revoke that
native permission. Strict exclusive release-object control requires switching
contributors to fork-based development without repository Write access. Do not
claim that a tag rule alone removes release editing/deletion permissions.

Production Databricks resources and protected source/review/run volumes must be
owned and managed by the maintainer. Contributor workspace access is limited to
development resources. Workspace/account/metastore administrators retain platform
authority; repository governance does not override platform administrators.

Phase 10 remains an experimental discharge-time model with aggregate-only
evaluation. This integration does not authorize clinical decisions, export trained
models, or add individual prediction endpoints.
