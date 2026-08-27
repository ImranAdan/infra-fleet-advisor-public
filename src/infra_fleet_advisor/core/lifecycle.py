from collections.abc import Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import PolicyBounds, Recommendation
from infra_fleet_advisor.core.validation import is_prior_recommendation_valid


@dataclass(frozen=True, slots=True)
class PriorRecommendation:
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


@dataclass(frozen=True, slots=True)
class PriorReport:
    recommendations: Sequence[PriorRecommendation]


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    recommendations: tuple[Recommendation, ...]
    new_count: int
    unchanged_count: int
    resolved_count: int
    suppressed_count: int


def _prior_as_recommendation(prior: PriorRecommendation, status: str) -> Recommendation:
    return Recommendation(
        fingerprint=prior.fingerprint,
        concern_key=prior.concern_key,
        category=prior.category,
        priority=prior.priority,
        title=prior.title,
        summary=prior.summary,
        evidence_ids=tuple(prior.evidence_ids),
        impact=prior.impact,
        suggested_change=prior.suggested_change,
        trade_offs=prior.trade_offs,
        confidence=prior.confidence,
        confidence_explanation=prior.confidence_explanation,
        status=status,
    )


def compare_with_prior(
    accepted: Sequence[Recommendation],
    prior: PriorReport | None,
    bounds: PolicyBounds,
    allowed_concern_keys: frozenset[str],
    collection_complete: bool,
) -> LifecycleResult:
    """Fingerprint identity drives comparison, not narrative text, so this
    stays stable once a real model reworks wording each run.

    A prior-report entry only gets republished if it passes the same
    publication gate a fresh candidate would (`is_prior_recommendation_valid`)
    — an untrusted prior report can't smuggle invented evidence, secrets, or
    invalid fields straight into the report. And it's only marked `resolved`
    when this run's collection was complete (`collection_complete`); if a
    collector was partial/failed, absence of evidence isn't proof the concern
    is gone, so it's carried forward as `unchanged` instead.
    """
    prior_by_fp = {p.fingerprint: p for p in prior.recommendations} if prior else {}

    results: list[Recommendation] = []
    new = unchanged = suppressed = 0
    for rec in accepted:
        if rec.concern_key in bounds.suppressed_concerns:
            results.append(rec.with_status("suppressed"))
            suppressed += 1
        elif rec.fingerprint in prior_by_fp:
            results.append(rec.with_status("unchanged"))
            unchanged += 1
        else:
            results.append(rec)
            new += 1

    current_fps = {rec.fingerprint for rec in accepted}
    resolved = 0
    for fp, prior_rec in prior_by_fp.items():
        if fp in current_fps or prior_rec.concern_key in bounds.suppressed_concerns:
            continue
        if not is_prior_recommendation_valid(prior_rec, bounds, allowed_concern_keys):
            continue
        if collection_complete:
            results.append(_prior_as_recommendation(prior_rec, "resolved"))
            resolved += 1
        else:
            results.append(_prior_as_recommendation(prior_rec, "unchanged"))
            unchanged += 1

    return LifecycleResult(tuple(results), new, unchanged, resolved, suppressed)
