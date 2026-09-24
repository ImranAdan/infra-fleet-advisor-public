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
| GitHub Actions | Tracked workflow settings, including Trivy scanning configuration and, per ECR-publishing job, whether a blocking Critical/High scan gates it through `needs` | Repository configuration only; exclusions and malformed or truncated input can leave coverage incomplete |
| Terraform IAM | Persistent-stack policies under `infrastructure/permanent/`; bounded JSON/HCL objects, local condition traversals and fixed-prefix resource ARN interpolation | Referenced policy documents and unknown decision fields remain partial within the persistent scope; no policy URL fetch or Terraform execution |
| Terraform cost | CloudWatch log-group retention (resources and the pinned EKS module's control-plane log group), ECR lifecycle policies, AWS provider `default_tags` cost-allocation keys, and EKS managed node-group bounds with node-autoscaler presence (Terraform and tracked `k8s/` text) under `infrastructure/` | Literal single-line values only; module log groups use published defaults for trusted majors; implicit AWS-created log groups are invisible, so C-003 cannot be proven satisfied |
| Dependency updates | Tracked dependency manifests (Dockerfiles, Python requirements, npm, Go, pinned Terraform, workflows) by directory, matched against `.github/dependabot.yml` | File names only; repository alert and security-update settings cannot be read, so S-010 is divergence-only |
| Kubernetes security | Tracked raw manifests under `k8s/`: ingress NetworkPolicy coverage of application pods (label-selector semantics, additive policies), permissive egress outside application namespaces (Flux's generated install excluded), Ingress TLS, cert-manager issuer and HTTP redirect, and RBAC bindings reaching a pod's mounted service-account token | Overlays are not rendered, so a profile patch could add a policy, binding or annotation; all four checks are divergence-only. Gateway API routes are not yet evaluated for S-005 |
| Kubernetes Deployments | Tracked raw `apps/v1` Deployment manifests under `k8s/`; rollout capacity (R-001) and container hardening (S-002) for owner-managed workloads under `k8s/applications/` | Does not render Helm or inspect a live cluster; missing, malformed, duplicate or truncated evidence remains unverified |
| Fleet lifecycle | The tracked `fleet` facade and fixed local and AWS strategy modules; closed lifecycle dispatch plus local pinned-tool, checkout-state, explicit-context, and next-command controls | Static shell structure only; it detects absent controls but cannot prove downloads, idempotence, runtime readiness, credential behavior, or teardown effects |

The security, reliability, cost and maintainability catalogs contain twenty
positions. Seventeen have registered checks. Unsupported positions and incomplete
evaluation remain explicit report coverage; the cost catalog has three checks
(log retention, cost tags and worker scaling are divergence-only), S-011's publication gate is
divergence-only because only recognised ECR login forms count as publication, and the maintainability catalog has two
divergence-only checks. They do
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

The lifecycle collector never executes Fleet code. It reads the fixed, bounded,
tracked `fleet` facade and the two named strategy modules, and recognizes only
the closed `local` and `aws-staging` dispatch shape. M-001 becomes divergent
when either profile lacks `setup`, `up`, or `down`. M-002 becomes divergent when
the local strategy lacks the pinned-tool installer, checkout-owned state,
explicit kubectl and Flux context, or the next startup command. Structurally
complete controls remain unverified because static shell inspection cannot
establish downloads, repeatability, runtime behavior, or successful teardown.
M-003 is divergent when the AWS strategy or `scripts/onboard-aws-profile.sh`
lacks plan-by-default setup, printed AWS and GitHub targets, stdin-only secret
writes, the next `up` command, or leaves the teardown workflow's
`destroy staging` confirmation to the operator rather than typing it itself.
Complete controls remain unverified: static text cannot prove any AWS, HCP
Terraform or GitHub call succeeds.

## Check drills

`drills/fleet-mutations.yaml` lists one literal, declared violation of the real
fleet per registered check. `infra-fleet-advisor drill` applies each in a
throwaway worktree, runs the ordinary review and requires the named
proposition to diverge; the nightly advisory workflow runs them as a separate,
read-only job. A drill reports `caught`, `missed` (the check no longer sees the
fleet), `stale` (the fleet no longer contains the drill's text) or
`already divergent` (the position cannot regress). Coverage counts a check
only as far as its drill proves it bites.

The first run found S-001 blind to credentials obtained inside local
composite actions such as `.github/actions/setup-aws-terraform`, which the
Terraform apply workflows use. The workflow collector now follows tracked
local composite actions one level deep.

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
