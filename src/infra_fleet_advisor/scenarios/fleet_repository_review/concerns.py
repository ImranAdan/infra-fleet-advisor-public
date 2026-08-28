from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import ConcernRule
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_IAM_WILDCARD,
    EVIDENCE_KIND_TRIVY_GATE,
)

CONCERN_STATIC_AWS_CREDENTIALS = "static_aws_credentials_in_ci"
CONCERN_TRIVY_IGNORE_UNFIXED = "trivy_ignore_unfixed"
CONCERN_WILDCARD_IAM_PERMISSIONS = "wildcard_iam_permissions"

# The deterministic support conditions for each concern: which evidence kind
# can back it, and which collector-derived facts must hold. A collector emits
# credential/trivy evidence for every step it finds, including correctly
# configured ones, so the facts — not the mere existence of evidence — are what
# make a claim publishable.
CONCERN_RULES: dict[str, ConcernRule] = {
    CONCERN_STATIC_AWS_CREDENTIALS: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
        required_facts={"uses_static_keys": True},
    ),
    CONCERN_TRIVY_IGNORE_UNFIXED: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_TRIVY_GATE,
        required_facts={"ignore_unfixed": True},
    ),
    CONCERN_WILDCARD_IAM_PERMISSIONS: ConcernRule(
        category="security",
        evidence_kind=EVIDENCE_KIND_IAM_WILDCARD,
    ),
}

ALLOWED_CONCERN_KEYS = frozenset(CONCERN_RULES)


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
}
