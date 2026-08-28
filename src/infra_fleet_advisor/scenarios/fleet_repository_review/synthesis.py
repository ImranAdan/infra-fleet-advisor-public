from dataclasses import dataclass
from typing import Protocol

from infra_fleet_advisor.core.contracts import RawRecommendationCandidate
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_STATIC_AWS_CREDENTIALS,
    CONCERN_TEMPLATES,
    CONCERN_TRIVY_IGNORE_UNFIXED,
    CONCERN_WILDCARD_IAM_PERMISSIONS,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_IAM_WILDCARD,
    EVIDENCE_KIND_TRIVY_GATE,
)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    enabled_categories: frozenset[str]
    max_recommendations: int


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    policy_context: PolicyContext
    evidence: tuple[Evidence, ...]
    # What is left of the run's wall-clock budget once collection has taken
    # its share. None means the caller imposes no deadline.
    remaining_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class SynthesisResponse:
    recommendations: tuple[RawRecommendationCandidate, ...]
    model_identifier: str


class Synthesizer(Protocol):
    model_identifier: str

    def synthesize(self, projection: EvidenceProjection) -> SynthesisResponse: ...


def _candidate_from_template(concern_key: str, evidence_id: str) -> RawRecommendationCandidate:
    t = CONCERN_TEMPLATES[concern_key]
    return RawRecommendationCandidate(
        concern_key=concern_key,
        category=t.category,
        priority=t.priority,
        title=t.title,
        summary=t.summary,
        evidence_ids=(evidence_id,),
        impact=t.impact,
        suggested_change=t.suggested_change,
        trade_offs=t.trade_offs,
        confidence=t.confidence,
        confidence_explanation=t.confidence_explanation,
    )


class StubSynthesizer:
    """Deterministic, pure stand-in for a real model call. A future
    AnthropicSynthesizer implements this same Synthesizer protocol against
    the same EvidenceProjection — only runtime/composition.py changes."""

    model_identifier = "stub-synthesizer-v1"

    def synthesize(self, projection: EvidenceProjection) -> SynthesisResponse:
        candidates: list[RawRecommendationCandidate] = []
        for item in projection.evidence:
            if item.kind == EVIDENCE_KIND_CREDENTIAL_METHOD and item.fact.get("uses_static_keys"):
                candidates.append(
                    _candidate_from_template(CONCERN_STATIC_AWS_CREDENTIALS, item.evidence_id)
                )
            elif item.kind == EVIDENCE_KIND_TRIVY_GATE and item.fact.get("ignore_unfixed"):
                candidates.append(
                    _candidate_from_template(CONCERN_TRIVY_IGNORE_UNFIXED, item.evidence_id)
                )
            elif item.kind == EVIDENCE_KIND_IAM_WILDCARD:
                candidates.append(
                    _candidate_from_template(CONCERN_WILDCARD_IAM_PERMISSIONS, item.evidence_id)
                )
        return SynthesisResponse(
            recommendations=tuple(candidates), model_identifier=self.model_identifier
        )
