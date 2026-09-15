# Implemented scope and coverage

[Documentation index](README.md)

## Supported product

The `fleet_repository_review` scenario reviews only
`ImranAdan/infra-fleet-public`. It verifies a complete Git snapshot, loads bounded
policy and Markdown intent, collects typed evidence, evaluates registered checks
and produces ranked recommendations in JSON and Markdown. Lifecycle comparison
tracks new, unchanged, resolved and suppressed findings against a prior report.

Recommendations require concrete repository evidence, expected impact,
suggested change, trade-offs and confidence. The report PR is the fleet
issue-creation decision record. See the [workflow](WORKFLOW.md) and
[publication guide](fleet-publication.md).

## Collector coverage

| Collector | Supported evidence | Limitations |
|---|---|---|
| GitHub Actions | Tracked workflow settings, including Trivy scanning configuration | Repository configuration only; exclusions and malformed or truncated input can leave coverage incomplete |
| Terraform IAM | Persistent-stack policies under `infrastructure/permanent/`; bounded JSON/HCL objects, local condition traversals and fixed-prefix resource ARN interpolation | Referenced policy documents and unknown decision fields remain partial within the persistent scope; no policy URL fetch or Terraform execution |
| Kubernetes Deployments | Tracked raw `apps/v1` Deployment manifests under `k8s/`; the reliability check evaluates owner-managed workloads under `k8s/applications/` | Does not render Helm or inspect a live cluster; missing, malformed, duplicate or truncated evidence remains unverified |
| Fleet lifecycle | The tracked `fleet` facade and fixed local strategy; closed profile and action dispatch for `setup`, `up`, and `down` | Static shell structure only; it detects an absent or inconsistent command surface but cannot prove idempotence, runtime readiness, credential behavior, or teardown effects |

The security, reliability, cost and maintainability catalogs contain twenty
positions. Four have registered checks. Unsupported positions and incomplete
evaluation remain explicit report coverage; the cost catalog has no registered
checks and the maintainability catalog has one divergence-only check. They do
not automatically create issues in either repository. The
[coverage review](COVERAGE-REVIEW.md) preserves the retired generated backlog.

Untracked Terraform downloads, including `.terraform` module files, are not
evidence. Workflow and IAM collectors apply policy exclusions and tracked-path
filtering before source-file limits. IAM collection follows the registered
persistent-stack scope, so an unparseable staging-only policy cannot make S-007
incomplete. Within that scope, the wildcard check does not establish effective
permissions after conditions and denies, and a referenced policy document remains
a visible gap because the advisor does not fetch it.

The rollout collector also records Flux's generated controllers, but R-001 is
scoped to owner-managed application manifests. Platform evidence remains
available for future platform-specific intent without generating application
rollout advice.

The lifecycle collector never executes Fleet code. It reads two fixed, bounded,
tracked files and recognizes only the closed `local` and `aws-staging` dispatch
shape. M-001 becomes divergent when either profile lacks `setup`, `up`, or
`down`. A complete surface remains unverified because static shell inspection
cannot establish the proposition's repeatability and failure behavior. M-002
and M-003 remain declared without checks until their implementation exposes
specific controls that trusted collectors can evaluate.

## Model support

`stub` is the default and runs the deterministic checks with templated wording.
The optional Anthropic synthesizer is implemented and tested against recorded
responses. Live model API validation is not part of the current baseline.
Deterministic checks and validation control which recommendations appear;
model-backed wording cannot invent findings or omit required divergences.

## What a report proves

A report captures repository desired state at one commit. It does not establish
that a private deployment matches that revision or that live infrastructure is
healthy. Incomplete relevant collection is deferred during fleet publication;
absence of evidence does not establish that the fleet is healthy.

The advisor does not deploy, merge fleet fixes or inspect AWS and Kubernetes.
The normal fix path is a maintainer-selected fleet agent. Optional
[mechanical remediation](remediation.md) and [decision feedback](feedback.md)
remain separate workflows.
