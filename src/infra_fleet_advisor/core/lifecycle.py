from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from infra_fleet_advisor.core.contracts import ConcernRule, PolicyBounds, Recommendation
from infra_fleet_advisor.core.evidence import Evidence
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
    # Carried so consumers can tell an active finding from one the owner
    # suppressed or that is already resolved. Lifecycle comparison itself does
    # not read this — it recomputes status from the current run.
    status: str = "new"
    owner_accepted_trade_off: str | None = None


@dataclass(frozen=True, slots=True)
class PriorReport:
    recommendations: Sequence[PriorRecommendation]
    evidence_by_id: Mapping[str, Evidence] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    recommendations: tuple[Recommendation, ...]
    new_count: int
    unchanged_count: int
    resolved_count: int
    suppressed_count: int


def _prior_as_recommendation(
    prior: PriorRecommendation, status: str, bounds: PolicyBounds
) -> Recommendation:
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
        owner_accepted_trade_off=bounds.accepted_trade_offs.get(prior.concern_key),
    )


def compare_with_prior(
    accepted: Sequence[Recommendation],
    prior: PriorReport | None,
    bounds: PolicyBounds,
    concern_rules: Mapping[str, ConcernRule],
    collector_status: Mapping[str, str],
) -> LifecycleResult:
    """Fingerprint identity drives comparison, not narrative text, so this
    stays stable once a real model reworks wording each run.

    A prior-report entry only gets republished if it passes the same
    publication gate a fresh candidate would (`is_prior_recommendation_valid`)
    — an untrusted prior report can't smuggle invented evidence, secrets, or
    invalid fields straight into the report. And it's only marked `resolved`
    when every collector that produced its cited evidence completed this run.
    An unrelated partial collector cannot reactivate the recommendation, while
    incomplete relevant coverage still carries it forward as `unchanged`.
    """
    # A malformed prior report could carry a non-string fingerprint (e.g. a
    # JSON list); guard the dict build so that alone can't crash the run.
    prior_by_fp = (
        {p.fingerprint: p for p in prior.recommendations if isinstance(p.fingerprint, str)}
        if prior
        else {}
    )
    prior_evidence = prior.evidence_by_id if prior else {}

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
        if not is_prior_recommendation_valid(prior_rec, bounds, concern_rules, prior_evidence):
            continue
        prior_collector_ids = {
            prior_evidence[evidence_id].collector_id for evidence_id in prior_rec.evidence_ids
        }
        relevant_collection_complete = bool(prior_collector_ids) and all(
            collector_status.get(collector_id) == "ok" for collector_id in prior_collector_ids
        )
        if relevant_collection_complete:
            results.append(_prior_as_recommendation(prior_rec, "resolved", bounds))
            resolved += 1
        else:
            results.append(_prior_as_recommendation(prior_rec, "unchanged", bounds))
            unchanged += 1

    return LifecycleResult(tuple(results), new, unchanged, resolved, suppressed)
