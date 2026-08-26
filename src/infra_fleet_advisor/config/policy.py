from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import PolicyBounds


@dataclass(frozen=True, slots=True)
class AcceptedTradeOff:
    concern_key: str
    rationale: str


@dataclass(frozen=True, slots=True)
class AdvisorPolicy:
    version: str
    max_recommendations: int
    max_wall_seconds: int
    max_model_calls: int
    enabled_categories: frozenset[str]
    category_priority: Mapping[str, int]
    accepted_trade_offs: Sequence[AcceptedTradeOff]
    suppressed_concerns: frozenset[str]
    evidence_path_exclusions: Sequence[str]

    def to_bounds(self) -> PolicyBounds:
        return PolicyBounds(
            enabled_categories=self.enabled_categories,
            category_priority=self.category_priority,
            max_recommendations=self.max_recommendations,
            suppressed_concerns=self.suppressed_concerns,
        )
