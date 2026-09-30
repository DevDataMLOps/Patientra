# Security policy

PATIENTRA is a healthcare-data engineering demonstration. It contains controls for safe
handling, but code alone does not make a workstation, cloud account, or organization
compliant with healthcare privacy or security requirements.

## Supported version

Security fixes target the latest version on the `main` branch. The current repository
release is `0.6.x`.

## Reporting a vulnerability

Do **not** open a public issue containing exploit details, credentials, patient data,
identifiers, protected paths, or screenshots.

Use GitHub's private vulnerability-reporting workflow from the repository **Security**
tab when it is available. If private reporting is unavailable, contact the repository
maintainers through GitHub and request a private channel before sharing details.

Include only the minimum information necessary:

- affected component and version;
- a synthetic reproduction;
- impact and realistic attack conditions;
- suggested mitigation, if known; and
- confirmation that no real patient data was used.

## Sensitive-data incidents

If sensitive data or a secret is committed, treat it as exposed even if the commit is
later deleted. Stop processing, revoke or rotate the secret, restrict access, notify the
data owner and security lead, preserve appropriate audit evidence, and follow the
organization's incident-response and breach-notification process.

For operational handling requirements, see [`docs/security.md`](docs/security.md).
