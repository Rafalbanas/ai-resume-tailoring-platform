# Security policy

## Supported versions

Security fixes are developed against the current `main` branch. Older commits
are not maintained as separate security release lines. Review changes and back
up your private application data before upgrading a deployment.

CVTailor is intended for owner-managed self-hosting. An optional demo account
can share `/login` while using separate credentials, sessions, storage and task
runtimes. The server selects the runtime from the authenticated session, never
from a request parameter. This is an application authorization boundary, not an
OS sandbox for mutually untrusted workloads. A browser context has one active
account; shared-origin XSS and server compromise remain security concerns.

Production document parsers and browser rendering must use separate owner/demo processing
services without account volumes or model credentials. Native children have kernel
socket restrictions, resource/time limits and bounded JSON input/output. Local CLI
subprocess mode shares the host filesystem; configure the isolated services for
untrusted input. See [processing budgets and deployment migration](docs/processing-security.md).

Model semantic approval is not proof that a natural summary is accurate. Web exports
require user confirmation for non-source summaries, bound to the summary and profile.
Controlled false-verdict tests and the live deployment inspection scope are documented
in the [security follow-up](docs/security-audit-2026-10-17-followup.md).

## Report a vulnerability privately

Use [GitHub's private vulnerability reporting form](https://github.com/Rafalbanas/ai-resume-tailoring-platform/security/advisories/new)
or open the repository's **Security → Advisories → Report a vulnerability** page.
Do not disclose an unpatched vulnerability in a public issue or pull request.

Include the affected commit or image revision, impact, deployment mode, and
minimal reproduction steps using synthetic data. Relevant areas include
authentication, sessions, CSRF, URL fetching/SSRF, uploads, document generation,
data exposure, and CI/CD credentials.

Do not attach real CVs, profile data, session cookies, `.env` files, API keys,
SSH keys, Kubernetes secrets, or unredacted logs. If sensitive information is
needed, agree on the minimum necessary details in the private report first.
Reproduce issues on your own instance; public deployments are not authorized
targets for security testing.

This is a personal project maintained on a best-effort basis. There is no
guaranteed response or resolution time. Use the private report to coordinate
verification, a fix, and any public disclosure with the maintainer.

For ordinary bugs and feature requests, use the public issue forms instead.
