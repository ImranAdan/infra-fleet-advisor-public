from collections.abc import Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import Recommendation


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


def compare_with_prior(
    accepted: Sequence[Recommendation],
    prior: PriorReport | None,
    suppressed_concerns: frozenset[str],
) -> LifecycleResult:
    """Fingerprint identity drives comparison, not narrative text, so this
    stays stable once a real model reworks wording each run."""
    prior_by_fp = {p.fingerprint: p for p in prior.recommendations} if prior else {}

    results: list[Recommendation] = []
    new = unchanged = suppressed = 0
    for rec in accepted:
        if rec.concern_key in suppressed_concerns:
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
        if fp in current_fps or prior_rec.concern_key in suppressed_concerns:
            continue
        results.append(
            Recommendation(
                fingerprint=prior_rec.fingerprint,
                concern_key=prior_rec.concern_key,
                category=prior_rec.category,
                priority=prior_rec.priority,
                title=prior_rec.title,
                summary=prior_rec.summary,
                evidence_ids=tuple(prior_rec.evidence_ids),
                impact=prior_rec.impact,
                suggested_change=prior_rec.suggested_change,
                trade_offs=prior_rec.trade_offs,
                confidence=prior_rec.confidence,
                confidence_explanation=prior_rec.confidence_explanation,
                status="resolved",
            )
        )
        resolved += 1

    return LifecycleResult(tuple(results), new, unchanged, resolved, suppressed)
