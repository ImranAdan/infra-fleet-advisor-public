# Security

## Reporting a vulnerability

For findings requiring confidential details, contact the repository owner
privately through an existing trusted channel before publishing them. GitHub
private vulnerability reporting is not currently enabled for this repository.
Public issues are appropriate for general security questions with sensitive
details removed.

Include the affected revision, a concise description, impact and a minimal
reproduction. Keep credentials, private infrastructure details and raw model
responses out of public issues and pull requests.

## Supported scope

Security fixes target the current `main` branch. The advisor's implemented
target is `ImranAdan/infra-fleet-public`; repository analysis evaluates desired
state at a verified Git commit, not a live AWS account or Kubernetes cluster.

## Access boundaries

| Path | Access and effect |
|---|---|
| Review | Public fleet read; writes a report in the advisor |
| Report delivery | Advisor-only contents and PR write; proposes a report PR |
| Approved issue publication | Fleet-only `issues: write`; creates deduplicated issues or resolution notes |
| Optional decision feedback | Fleet `issues: read`; proposes policy in the advisor |
| Optional mechanical remediation | Separate fleet contents and PR write credential; proposes a narrow fix PR |

Reviewing does not modify fleet code or runtime infrastructure. Publication
uses a separate App token scoped to the fixed fleet repository and cannot
close or reopen issues. No workflow merges a fleet fix or starts a fixing
agent. See the [publication](docs/fleet-publication.md),
[feedback](docs/feedback.md) and [remediation](docs/remediation.md) guides for
their separate configuration.

## Untrusted inputs and approval

Repository text, prior reports, scanner output, issue prose and model output
are untrusted. Deterministic code verifies source identity, bounds input sizes,
validates evidence paths and citations, and controls publication eligibility.
Prose cannot enable tools, relax policy or add collectors.

Fleet publication runs trusted default-branch code. It verifies a merged
report-only PR, uses that merge commit's report and links new issues to the
approving PR. Current policy and intent must match; incomplete relevant
collection is deferred. Live-main freshness is rechecked before the write
token is acquired and before publication. Fetched code is compared as data
and never executed. These checks do not lock repository merges.

Optional feedback uses validated issue labels and state, not issue titles,
bodies or comments. Optional model synthesis improves wording around captured
evidence; it cannot invent a finding or omit a required divergence.

## Security checks

PR CI runs lint security rules, strict typing, deterministic tests, workflow
lint and Trivy. Deliberately insecure test fixtures are excluded from Trivy;
they remain part of collector tests. Check
[current coverage](docs/status.md) before interpreting a clean report as
assurance about areas the advisor cannot evaluate.
