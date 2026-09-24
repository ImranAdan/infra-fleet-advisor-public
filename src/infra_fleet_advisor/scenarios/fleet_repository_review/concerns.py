from collections.abc import Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import ConcernRule, RawRecommendationCandidate
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
    EVIDENCE_KIND_IAM_WILDCARD,
    EVIDENCE_KIND_TRIVY_GATE,
    GHA_COLLECTOR_ID,
    K8S_DEPLOYMENT_COLLECTOR_ID,
    TF_IAM_COLLECTOR_ID,
)

CONCERN_STATIC_AWS_CREDENTIALS = "static_aws_credentials_in_ci"
CONCERN_CI_CREDENTIALS_WITHOUT_OIDC = "ci_credentials_without_oidc"
CONCERN_TRIVY_IGNORE_UNFIXED = "trivy_ignore_unfixed"
CONCERN_WILDCARD_IAM_PERMISSIONS = "wildcard_iam_permissions"
CONCERN_DEPLOYMENT_ROLLOUT_CAPACITY = "deployment_rollout_capacity_loss"
CONCERN_FLEET_LIFECYCLE_INCOMPLETE = "fleet_profile_lifecycle_incomplete"
CONCERN_FLEET_LOCAL_FIRST_USE_INCOMPLETE = "fleet_local_first_use_incomplete"
CONCERN_FLEET_AWS_ONBOARDING_INCOMPLETE = "fleet_aws_onboarding_incomplete"
CONCERN_CONTAINER_HARDENING_INCOMPLETE = "container_hardening_incomplete"
CONCERN_LOG_RETENTION_UNBOUNDED = "staging_log_retention_unbounded"
CONCERN_ECR_RETENTION_UNBOUNDED = "ecr_image_retention_unbounded"
CONCERN_DEPENDENCY_UPDATES_MISSING = "dependency_updates_not_configured"
CONCERN_COST_TAGS_MISSING = "cost_allocation_tags_missing"
CONCERN_ECR_PUBLICATION_UNGATED = "ecr_publication_not_scan_gated"

# The deterministic support conditions for each concern: which evidence kind
# can back it, and which collector-derived facts must hold. A collector emits
# credential/trivy evidence for every step it finds, including correctly
# configured ones, so the facts — not the mere existence of evidence — are what
# make a claim publishable.
CONCERN_RULES: dict[str, ConcernRule] = {
    CONCERN_STATIC_AWS_CREDENTIALS: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
        collector_id=GHA_COLLECTOR_ID,
        required_facts={"uses_static_keys": True},
    ),
    CONCERN_TRIVY_IGNORE_UNFIXED: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_TRIVY_GATE,
        collector_id=GHA_COLLECTOR_ID,
        required_facts={"ignore_unfixed": True},
    ),
    CONCERN_WILDCARD_IAM_PERMISSIONS: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_IAM_WILDCARD,
        collector_id=TF_IAM_COLLECTOR_ID,
    ),
    CONCERN_DEPLOYMENT_ROLLOUT_CAPACITY: ConcernRule(
        category="reliability",
        evidence_kind=EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
        collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
        required_facts={"retains_healthy_capacity": False},
    ),
}


@dataclass(frozen=True, slots=True)
class ConcernTemplate:
    category: str
    priority: str
    title: str
    summary: str
    impact: str
    suggested_change: str
    trade_offs: str
    confidence: float
    confidence_explanation: str


CONCERN_TEMPLATES: dict[str, ConcernTemplate] = {
    CONCERN_CI_CREDENTIALS_WITHOUT_OIDC: ConcernTemplate(
        category="security",
        priority="high",
        title="CI workflow does not use OIDC-only AWS credentials",
        summary=(
            "A GitHub Actions step cannot establish an exclusive short-lived "
            "OIDC role-to-assume flow from its permissions and action inputs."
        ),
        impact="Long-lived or ambient credentials widen the blast radius of CI compromise.",
        suggested_change=(
            "Grant the job id-token: write, configure role-to-assume, remove static-key "
            "inputs, and keep credential-reuse and OIDC-bypass inputs disabled."
        ),
        trade_offs="Requires provisioning and trusting an OIDC IAM role for this workflow.",
        confidence=0.9,
        confidence_explanation=(
            "Directly observed from effective workflow/job permissions and the step's `with:` keys."
        ),
    ),
    CONCERN_STATIC_AWS_CREDENTIALS: ConcernTemplate(
        category="security",
        priority="high",
        title="CI workflow uses long-lived AWS keys instead of OIDC",
        summary=(
            "A GitHub Actions step configures AWS credentials with static "
            "access keys rather than an OIDC role-to-assume."
        ),
        impact="Long-lived keys widen the blast radius of a leaked CI secret.",
        suggested_change=(
            "Switch the step to aws-actions/configure-aws-credentials with role-to-assume."
        ),
        trade_offs="Requires provisioning and trusting an OIDC IAM role for this workflow.",
        confidence=0.9,
        confidence_explanation="Directly observed from the workflow step's `with:` keys.",
    ),
    CONCERN_TRIVY_IGNORE_UNFIXED: ConcernTemplate(
        category="security",
        priority="medium",
        title="Trivy CI gate ignores unfixed vulnerabilities",
        summary=(
            "The Trivy scan step sets ignore-unfixed, so Critical/High findings "
            "without an available fix do not block the pipeline."
        ),
        impact="Unpatchable-but-known vulnerabilities can reach a published image undetected.",
        suggested_change=(
            "Remove ignore-unfixed, or pair it with a documented, time-boxed exception process."
        ),
        trade_offs="May block builds on vulnerabilities with no vendor fix yet available.",
        confidence=0.85,
        confidence_explanation="Directly observed from the trivy-action step's `with:` keys.",
    ),
    CONCERN_WILDCARD_IAM_PERMISSIONS: ConcernTemplate(
        category="security",
        priority="critical",
        title="IAM policy grants a wildcard action on all resources",
        summary=(
            "A Terraform-managed IAM policy statement allows a wildcard action "
            "(e.g. service:*) with Resource set to *."
        ),
        impact=(
            "Overly broad IAM grants expand the blast radius if the associated role's "
            "credentials are compromised, and make least-privilege review difficult."
        ),
        suggested_change=(
            "Scope the action list to the specific API calls required, and constrain "
            "Resource to the specific ARNs the role needs instead of *."
        ),
        trade_offs=(
            "Narrowing permissions may require iterating as new resource types are "
            "added, and risks under-provisioning if scoped too tightly."
        ),
        confidence=0.85,
        confidence_explanation="Directly observed from the IAM policy's parsed statement.",
    ),
    CONCERN_DEPLOYMENT_ROLLOUT_CAPACITY: ConcernTemplate(
        category="reliability",
        priority="high",
        title="Deployment rollout can reduce healthy capacity",
        summary=(
            "A declared Kubernetes Deployment can make existing healthy capacity unavailable "
            "before replacement capacity is ready."
        ),
        impact=(
            "A routine rollout can interrupt service or reduce the workload below its declared "
            "replica capacity."
        ),
        suggested_change=(
            "Use RollingUpdate with an effective maxUnavailable of 0 and a positive maxSurge, "
            "and define a readiness probe for every application container."
        ),
        trade_offs=(
            "Zero-unavailable rollouts temporarily consume surge capacity and may require extra "
            "cluster headroom."
        ),
        confidence=0.95,
        confidence_explanation=(
            "Calculated directly from the Deployment replicas, rollout fenceposts, and container "
            "readiness probes in repository desired state."
        ),
    ),
    CONCERN_FLEET_LIFECYCLE_INCOMPLETE: ConcernTemplate(
        category="maintainability",
        priority="high",
        title="Fleet profiles lack the declared lifecycle command surface",
        summary=(
            "The tracked Fleet facade does not route setup, up, and down through both "
            "the local and AWS staging profile strategies."
        ),
        impact=(
            "A new adopter must leave the common interface and complete profile-specific "
            "manual steps before the platform can be used."
        ),
        suggested_change=(
            "Add setup to the fixed ./fleet action surface and implement it for local and "
            "aws-staging. Local setup should prepare and validate pinned tools; AWS setup "
            "should validate adopter configuration and sessions, configure GitHub and HCP "
            "Terraform, and bootstrap the OIDC foundation. Preserve the existing bounded "
            "teardown behavior."
        ),
        trade_offs=(
            "Automated AWS onboarding expands the facade's credential and provider API surface, "
            "so target validation and explicit confirmation must precede mutations."
        ),
        confidence=0.95,
        confidence_explanation=(
            "Derived from the closed action allowlist and fixed local and AWS dispatch branches."
        ),
    ),
    CONCERN_FLEET_LOCAL_FIRST_USE_INCOMPLETE: ConcernTemplate(
        category="maintainability",
        priority="high",
        title="Local setup lacks the declared first-use controls",
        summary=(
            "The tracked local profile does not expose the complete static contract for "
            "checkout-owned pinned tools, an explicit Kubernetes context, and a next command."
        ),
        impact=(
            "A new contributor can be left to assemble version-sensitive tooling manually or "
            "risk operating on an unrelated default Kubernetes context."
        ),
        suggested_change=(
            "Have local setup install checksum-verified kind, kubectl, and Flux binaries into "
            "checkout-owned state; prefer that tool directory for later commands, bind kubectl "
            "and Flux to the owned kubeconfig and context, and print the next lifecycle command."
        ),
        trade_offs=(
            "Setup needs network access for the first verified download and the repository must "
            "maintain checksums for each supported operating-system and architecture pair."
        ),
        confidence=0.95,
        confidence_explanation=(
            "Derived from bounded, tracked local-strategy source without executing Fleet code."
        ),
    ),
    CONCERN_FLEET_AWS_ONBOARDING_INCOMPLETE: ConcernTemplate(
        category="maintainability",
        priority="high",
        title="AWS staging lifecycle lacks a declared onboarding or teardown control",
        summary=(
            "The aws-staging strategy or its onboarding coordinator does not show every static "
            "control: plan-by-default setup, reported targets, stdin-only secrets, a next "
            "command, and a teardown confirmation typed by the operator."
        ),
        impact=(
            "An adopter can mutate or destroy a billable AWS target without first seeing and "
            "confirming it, or leak a credential through process arguments."
        ),
        suggested_change=(
            "Keep setup in plan mode unless --apply is given, print the AWS and GitHub targets "
            "before mutation, pipe secrets to gh secret set, print the next lifecycle command, "
            "and have down show its target and pass the operator's typed confirmation to the "
            "teardown workflow instead of a hard-coded one."
        ),
        trade_offs=(
            "Interactive confirmation makes unattended teardown require an explicit, "
            "separately supplied confirmation value."
        ),
        confidence=0.9,
        confidence_explanation=(
            "Derived from fixed, tracked shell text of the AWS strategy and onboarding "
            "coordinator without executing them."
        ),
    ),
    CONCERN_CONTAINER_HARDENING_INCOMPLETE: ConcernTemplate(
        category="security",
        priority="high",
        title="Application container runs without the declared hardening",
        summary=(
            "A Deployment under k8s/applications has a container that is not constrained to "
            "a non-root user, with privilege escalation disabled and all capabilities dropped."
        ),
        impact=(
            "A compromised process keeps root or kernel capabilities it does not need, widening "
            "what an attacker can do inside the node."
        ),
        suggested_change=(
            "Set runAsNonRoot (or a non-zero runAsUser), allowPrivilegeEscalation: false and "
            "capabilities.drop: [ALL] on every container and init container, adding back no "
            "capabilities."
        ),
        trade_offs=(
            "Images that bind low ports or write as root need rebuilding or a documented, "
            "narrow capability exception."
        ),
        confidence=0.95,
        confidence_explanation=(
            "Derived from pod and container securityContext fields in repository desired state; "
            "admission mutation and live pods are not inspected."
        ),
    ),
    CONCERN_LOG_RETENTION_UNBOUNDED: ConcernTemplate(
        category="cost",
        priority="medium",
        title="Staging CloudWatch log group keeps logs longer than 30 days",
        summary=(
            "A staging log group declared directly or created by a pinned module retains events "
            "for more than 30 days or never expires them."
        ),
        impact=(
            "Log storage grows with every rebuild cycle and is billed after the staging "
            "environment's usefulness for debugging has passed."
        ),
        suggested_change=(
            "Declare an explicit retention of at most 30 days, for the EKS module via "
            "cloudwatch_log_group_retention_in_days, or document why longer retention is needed."
        ),
        trade_offs=(
            "Shorter retention removes older control-plane audit trails that could help a late "
            "incident investigation."
        ),
        confidence=0.9,
        confidence_explanation=(
            "Read from literal Terraform attributes; module log groups use the published defaults "
            "of the pinned major version without downloading the module."
        ),
    ),
    CONCERN_ECR_RETENTION_UNBOUNDED: ConcernTemplate(
        category="cost",
        priority="medium",
        title="ECR repository retains images without a bounded lifecycle",
        summary=(
            "A Terraform-managed ECR repository has no lifecycle policy that both expires "
            "untagged images and bounds the number or age of every retained image."
        ),
        impact="Image storage grows with every build and is billed indefinitely.",
        suggested_change=(
            "Attach an aws_ecr_lifecycle_policy with an expire rule for tagStatus any (or "
            "untagged plus all tagged images) using imageCountMoreThan or sinceImagePushed."
        ),
        trade_offs=(
            "Expired images can no longer be used for rollback; retain the rollback window "
            "explicitly."
        ),
        confidence=0.9,
        confidence_explanation=(
            "Joined from literal repository and lifecycle-policy resources in one root module."
        ),
    ),
    CONCERN_DEPENDENCY_UPDATES_MISSING: ConcernTemplate(
        category="security",
        priority="medium",
        title="Tracked dependency manifests have no Dependabot update entry",
        summary=(
            "A tracked manifest directory (a Dockerfile, Python requirements, Terraform "
            "providers, workflows) has no matching Dependabot package-ecosystem entry."
        ),
        impact=(
            "Pinned versions and image digests in that directory never receive routine or "
            "security update pull requests and silently age."
        ),
        suggested_change=(
            "Add a monthly Dependabot entry for that ecosystem and directory, grouped like the "
            "existing entries, or remove the unused manifest."
        ),
        trade_offs="More dependency pull requests to review each month.",
        confidence=0.9,
        confidence_explanation=(
            "Matched tracked file names against the committed Dependabot configuration; "
            "repository alert settings are outside the template."
        ),
    ),
    CONCERN_COST_TAGS_MISSING: ConcernTemplate(
        category="cost",
        priority="medium",
        title="Terraform resources lack cost-allocation tags",
        summary=(
            "Resources in a root module set tags that lack an environment, service or owner "
            "key, and the AWS provider's default_tags do not supply the missing keys."
        ),
        impact=(
            "Billed usage of the listed resources, and of any other resource that does not tag "
            "itself, may go unattributed when the bill is split by environment, service or owner."
        ),
        suggested_change=(
            "Add default_tags { tags = { Environment, Service, Owner } } to every aws provider, "
            "for example from a shared local, and activate the keys as cost-allocation tags."
        ),
        trade_offs=(
            "Changing default tags updates every taggable resource on the next apply; some "
            "resources, such as instances launched by node groups, still need tag propagation."
        ),
        confidence=0.9,
        confidence_explanation=(
            "Read from literal provider default_tags, resolving one level of local reference."
        ),
    ),
    CONCERN_ECR_PUBLICATION_UNGATED: ConcernTemplate(
        category="security",
        priority="high",
        title="ECR publication is not gated by a blocking Critical/High scan",
        summary=(
            "A workflow job that logs in to ECR is not preceded, in its own steps or through "
            "needs, by a Trivy step that fails on Critical or High findings."
        ),
        impact="An image with a known, fixable Critical or High vulnerability can be published.",
        suggested_change=(
            "Run Trivy with severity CRITICAL,HIGH and a non-zero exit-code before the ECR login, "
            "or in a job the publishing job needs, without always(), failure() or cancelled() "
            "overriding that dependency."
        ),
        trade_offs="A new upstream CVE can block an otherwise unchanged release until triaged.",
        confidence=0.9,
        confidence_explanation=(
            "Derived from workflow job dependencies, conditions and Trivy step inputs."
        ),
    ),
}


def candidate_from_template(
    concern_key: str,
    evidence_ids: Sequence[str],
    priority: str | None = None,
) -> RawRecommendationCandidate:
    """Build trusted fallback wording for a deterministically proven divergence."""
    template = CONCERN_TEMPLATES[concern_key]
    return RawRecommendationCandidate(
        concern_key=concern_key,
        category=template.category,
        priority=priority or template.priority,
        title=template.title,
        summary=template.summary,
        evidence_ids=tuple(evidence_ids),
        impact=template.impact,
        suggested_change=template.suggested_change,
        trade_offs=template.trade_offs,
        confidence=template.confidence,
        confidence_explanation=template.confidence_explanation,
    )
