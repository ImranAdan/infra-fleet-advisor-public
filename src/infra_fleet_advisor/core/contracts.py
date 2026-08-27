import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

PRIORITIES = ("critical", "high", "medium", "low")
STATUSES = ("new", "unchanged", "resolved", "suppressed")


@dataclass(frozen=True, slots=True)
class RawRecommendationCandidate:
    """Closed, untrusted synthesizer output. Every field is inert data until
    core.validation accepts it — never interpolated into control flow."""

    concern_key: str
    category: str
    priority: str
    title: str
    summary: str
    evidence_ids: Sequence[str]
    impact: str
    suggested_change: str
    trade_offs: str
    confidence: float
    confidence_explanation: str


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Only core.validation.validate_candidates constructs these directly."""

    fingerprint: str
    concern_key: str
    category: str
    priority: str
    title: str
    summary: str
    evidence_ids: Sequence[str]
    impact: str
    suggested_change: str
    trade_offs: str
    confidence: float
    confidence_explanation: str
    status: str
    rank: int | None = None
    rank_rationale: str | None = None
    owner_accepted_trade_off: str | None = None

    def with_status(self, status: str) -> "Recommendation":
        return replace(self, status=status)

    def with_rank(self, rank: int | None, rationale: str | None) -> "Recommendation":
        return replace(self, rank=rank, rank_rationale=rationale)


@dataclass(frozen=True, slots=True)
class PolicyBounds:
    """Pure core projection of AdvisorPolicy, so core doesn't depend on config."""

    enabled_categories: frozenset[str]
    category_priority: Mapping[str, int]
    max_recommendations: int
    suppressed_concerns: frozenset[str]
    accepted_trade_offs: Mapping[str, str] = field(default_factory=dict)


def compute_fingerprint(category: str, concern_key: str, evidence_ids: Sequence[str]) -> str:
    """Depends only on category/concern_key/evidence identity, never narrative
    text, so reworded output across runs still fingerprints identically."""
    canonical = "|".join([category, concern_key, *sorted(set(evidence_ids))])
    return "fp_" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
