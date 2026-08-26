from dataclasses import dataclass

CONCERN_STATIC_AWS_CREDENTIALS = "static_aws_credentials_in_ci"
CONCERN_TRIVY_IGNORE_UNFIXED = "trivy_ignore_unfixed"

ALLOWED_CONCERN_KEYS = frozenset({CONCERN_STATIC_AWS_CREDENTIALS, CONCERN_TRIVY_IGNORE_UNFIXED})


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
}
