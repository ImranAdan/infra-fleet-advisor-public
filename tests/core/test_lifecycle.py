from infra_fleet_advisor.core.contracts import Recommendation
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport, compare_with_prior


def _rec(fingerprint: str, concern_key: str = "concern", status: str = "new") -> Recommendation:
    return Recommendation(
        fingerprint=fingerprint,
        concern_key=concern_key,
        category="security",
        priority="high",
        title="t",
        summary="s",
        evidence_ids=("e1",),
        impact="i",
        suggested_change="c",
        trade_offs="t",
        confidence=0.9,
        confidence_explanation="e",
        status=status,
    )


def _prior_rec(fingerprint: str, concern_key: str = "concern") -> PriorRecommendation:
    return PriorRecommendation(
        fingerprint=fingerprint,
        concern_key=concern_key,
        category="security",
        priority="high",
        title="t",
        summary="s",
        evidence_ids=("e1",),
        impact="i",
        suggested_change="c",
        trade_offs="t",
        confidence=0.9,
        confidence_explanation="e",
    )


def test_new_unchanged_resolved_suppressed() -> None:
    prior = PriorReport(
        recommendations=[_prior_rec("fp_unchanged"), _prior_rec("fp_resolved", "resolved_concern")]
    )
    accepted = [_rec("fp_unchanged"), _rec("fp_new", "new_concern")]

    result = compare_with_prior(accepted, prior, suppressed_concerns=frozenset())

    statuses = {r.fingerprint: r.status for r in result.recommendations}
    assert statuses["fp_unchanged"] == "unchanged"
    assert statuses["fp_new"] == "new"
    assert statuses["fp_resolved"] == "resolved"
    assert result.new_count == 1
    assert result.unchanged_count == 1
    assert result.resolved_count == 1


def test_suppressed_concern_marked_suppressed_not_new() -> None:
    accepted = [_rec("fp_a", "muted_concern")]
    result = compare_with_prior(accepted, None, suppressed_concerns=frozenset({"muted_concern"}))
    assert result.recommendations[0].status == "suppressed"
    assert result.suppressed_count == 1
    assert result.new_count == 0


def test_no_prior_report_everything_is_new() -> None:
    result = compare_with_prior([_rec("fp_a")], None, frozenset())
    assert result.new_count == 1
    assert result.resolved_count == 0
