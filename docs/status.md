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
| Terraform cost | CloudWatch log-group retention (resources and the pinned EKS module's control-plane log group), ECR lifecycle policies, AWS provider `default_tags` cost-allocation keys, EKS managed node-group bounds with statically enabled node-autoscaler presence, EKS public-endpoint exposure by root module (S-006), and scheduled release of staging capacity through an `aws_autoscaling_schedule` to zero or a scheduled workflow that destroys Terraform or runs `./fleet down --profile aws-staging` (C-001) | Literal values only; dynamic `count`/`for_each` enablement remains unverified. Module log groups use published defaults for trusted majors; implicit AWS-created log groups are invisible, so C-003 cannot be proven satisfied |
| Dependency updates | Tracked dependency manifests (Dockerfiles, Python requirements, npm, Go, pinned Terraform, workflows) by directory, matched against `.github/dependabot.yml` | File names only; repository alert and security-update settings cannot be read, so S-010 is divergence-only |
| Application config | Literal `app.config[...]` session-cookie settings in tracked Flask applications under `applications/`, parsed with `ast` and never imported | Module-level literals only; runtime overrides are invisible, so S-008 is divergence-only |
| Kubernetes security | What each deployment profile applies: every `k8s/clusters/<profile>` is rendered in-process (Flux Kustomization paths, local `resources`, inline JSON6902 patches, `namespace`, stable-name `configMapGenerator`, and Flux substitution of values declared in Git). Evaluates ingress NetworkPolicy coverage of application pods, permissive egress outside application namespaces, Ingress TLS/issuer/redirect and RBAC reaching mounted tokens; protective facts must hold in every profile | Flux sources must be the bootstrap source or declare `infra-fleet.io/checkout-mirror: "true"`; other sources, remote bases, strategic-merge patches, hashed or `envs` generators, unknown kustomize fields or untracked files make a profile incomplete. Variables from sources created outside Git (bootstrap ConfigMaps, Secrets) stay literal, and HelmRelease chart output is not rendered. S-003, S-004 and S-009 can be satisfied; S-005 stays divergence-only until Gateway API listeners are evaluated |
| Kubernetes Deployments | Rendered `apps/v1` Deployments in every profile; rollout capacity (R-001) and container hardening (S-002) for owner-managed workloads sourced from `k8s/applications/` | Uses the same closed kustomize subset as the security collector; does not render Helm or inspect a live cluster, and incomplete profiles remain unverified |
| Fleet lifecycle | The tracked `fleet` facade and fixed local and AWS strategy modules; closed lifecycle dispatch plus local pinned-tool, checkout-state, explicit-context, and next-command controls | Static shell structure only; it detects absent controls but cannot prove downloads, idempotence, runtime readiness, credential behavior, or teardown effects |

The security, reliability, cost and maintainability catalogs contain twenty
positions. All twenty have registered checks. Unsupported positions and incomplete
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

The deployment collector combines one workload's facts across rendered
profiles, so a rollout or hardening control must hold everywhere. It also
records Flux's generated controllers, but R-001 and S-002 are scoped to
owner-managed application manifests. Platform evidence remains available for
future platform-specific intent without generating application advice.

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
proposition to diverge; the nightly advisory workflow and every pull request (the Quality workflow)
run them as a separate, read-only job. A drill reports `caught`, `missed` (the check no longer sees the
fleet), `stale` (the fleet no longer contains the drill's text) or
`already divergent` (the position cannot regress). Coverage counts a check
only as far as its drill proves it bites.

The first run found S-001 blind to credentials obtained inside local
composite actions such as `.github/actions/setup-aws-terraform`, which the
Terraform apply workflows use. The workflow collector now follows tracked
local composite actions one level deep.

## Ratchet guard

Drills prove each check can fire; the ratchet guard proves an advisor change
did not quietly lose ground. On every pull request, `scripts/ratchet-guard.sh`
reviews one fleet commit twice, with the base advisor's code, catalog and policy
and with the proposed ones, and `infra-fleet-advisor ratchet` compares them.
The fleet is held constant, so every difference is the advisor's doing. It
fails (exit 8) on lost proof, a lost check, or a divergence that became
satisfied; new proof and new findings are reported. A slip can be right, such
as a fixed false positive, so the pull request must say why.

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
