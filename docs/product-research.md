# Product research

## Research subject

Infra Fleet Advisor is intentionally bound to
[`infra-fleet-public`](https://github.com/ImranAdan/infra-fleet-public). The
initial research snapshot used the local checkout at commit `f03f7ad` on
2026-08-26.

The fleet presents itself as an opinionated AWS EKS platform demonstrating
GitOps, progressive delivery, observability, security automation, and explicit
cost controls. It is also a learning and staging platform: some availability,
security, and operational trade-offs are intentionally accepted to keep cost
and complexity proportionate.

That context matters. The advisor must judge the fleet against its own intent,
not against an imaginary production platform with unlimited budget and uptime
requirements.

## Available evidence surfaces

The repository already contains rich, complementary signals:

- Terraform for permanent and ephemeral AWS infrastructure;
- Kubernetes and Flux desired state;
- Helm releases, image automation, HPA, Flagger, and Prometheus configuration;
- GitHub Actions for planning, validation, deployment, rebuild, destruction,
  release, and health verification;
- Trivy, schema, policy, and workflow validation;
- application code and tests for LoadHarness;
- cost estimates and deliberate cost-saving decisions;
- security findings, operational guidance, design decisions, and roadmaps; and
- Git history showing when desired state and documented intent changed.

These are not merely files to summarize. Together they describe intended
state, existing controls, known exceptions, and unresolved work.

## Observed product opportunities

### Fragmented findings

Potential improvements are distributed across scanners, workflow logs,
comments, TODOs, roadmaps, and security documentation. A maintainer must
manually reconcile them and decide which still matter.

### Context-free best practices

Generic infrastructure scanners can flag technical conditions but do not know
why the fleet uses nightly destruction, Spot instances, a single NAT gateway,
limited replicas, or deliberately disabled components. An advisor can relate a
finding to those documented trade-offs before recommending change.

### Drift between intent and desired state

Documentation, workflow behavior, Terraform, and Kubernetes configuration can
evolve independently. Cross-file inconsistencies are well suited to
evidence-grounded synthesis.

### Recommendation lifecycle

One-off reports quickly become noise. Stable fingerprints and comparison with
prior runs can distinguish a new issue from an accepted risk, an unchanged
finding, or a resolved recommendation.

## Example evidence, not validated recommendations

The research snapshot includes broad IAM permissions, permissive application
egress, documented security backlog items, disabled components chosen for cost,
and version-sensitive platform dependencies. These examples demonstrate why
context and prioritization matter. They are not pre-approved findings and must
be re-evaluated from a verified source snapshot before appearing in a report.

## Product implications

1. The Git repository is the only required source for the MVP.
2. Existing deterministic tools should be collectors, not replaced by an LLM.
3. Owner policy must capture intentional trade-offs and accepted risks.
4. Every published claim must point to evidence captured during the same run.
5. The report must be short and prioritized rather than exhaustive.
6. Read-only operation is a product feature and a security boundary.
7. Live cluster data may improve later recommendations, but it is not required
   to validate the initial product.
8. Fleet decisions should return as a closed, typed signal rather than prose:
   issue state plus a small reason-label vocabulary can propose policy without
   making comments or issue descriptions trusted input.
