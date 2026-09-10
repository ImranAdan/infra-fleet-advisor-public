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
