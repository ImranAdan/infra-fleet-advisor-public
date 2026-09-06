from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from infra_fleet_advisor.core.contracts import ConcernRule, RawRecommendationCandidate
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_RULES,
    candidate_from_template,
)


@dataclass(frozen=True, slots=True)
class PolicyContext:
    enabled_categories: frozenset[str]
    max_recommendations: int
    concern_rules: Mapping[str, ConcernRule] | None = None
    intent_propositions: tuple["IntentContext", ...] = ()


@dataclass(frozen=True, slots=True)
class IntentContext:
    document_id: str
    proposition_id: str
    check_key: str
    concern_key: str
    statement: str


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


class StubSynthesizer:
    """Deterministic, pure stand-in for a real model call. A future
    AnthropicSynthesizer implements this same Synthesizer protocol against
    the same EvidenceProjection — only runtime/composition.py changes."""

    model_identifier = "stub-synthesizer-v1"

    def synthesize(self, projection: EvidenceProjection) -> SynthesisResponse:
        candidates: list[RawRecommendationCandidate] = []
        configured_rules = projection.policy_context.concern_rules
        rules = CONCERN_RULES if configured_rules is None else configured_rules
        for item in projection.evidence:
            for concern_key, rule in sorted(rules.items()):
                if rule.category not in projection.policy_context.enabled_categories:
                    continue
                if item.kind != rule.evidence_kind:
                    continue
                if rule.source_path_prefixes and not any(
                    item.source_path == prefix or item.source_path.startswith(f"{prefix}/")
                    for prefix in rule.source_path_prefixes
                ):
                    continue
                if any(item.fact.get(key) != value for key, value in rule.required_facts.items()):
                    continue
                candidates.append(
                    candidate_from_template(concern_key, (item.evidence_id,), rule.priority)
                )
        return SynthesisResponse(
            recommendations=tuple(candidates), model_identifier=self.model_identifier
        )
