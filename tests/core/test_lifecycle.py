from dataclasses import replace

from infra_fleet_advisor.core.contracts import ConcernRule, PolicyBounds, Recommendation
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport, compare_with_prior

ALLOWED = {
    key: ConcernRule(category="security", evidence_kind="k")
    for key in ("concern", "new_concern", "resolved_concern", "muted_concern")
}


def _evidence(kind: str = "k", **fact) -> dict[str, Evidence]:
    """The evidence table a real prior report carries for its own citations."""
    return {
        "e1": Evidence(
            evidence_id="e1",
            kind=kind,
            source_path="a.yml",
            locator="loc",
            excerpt="e",
            fact=fact,
        )
    }


def _bounds(suppressed: frozenset = frozenset()) -> PolicyBounds:
    return PolicyBounds(
        enabled_categories=frozenset({"security"}),
        category_priority={"security": 10},
        max_recommendations=10,
        suppressed_concerns=suppressed,
    )


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


def _prior_rec(fingerprint: str, concern_key: str = "concern", **overrides) -> PriorRecommendation:
    base = {
        "fingerprint": fingerprint,
        "concern_key": concern_key,
        "category": "security",
        "priority": "high",
        "title": "t",
        "summary": "s",
        "evidence_ids": ("e1",),
        "impact": "i",
        "suggested_change": "c",
        "trade_offs": "t",
        "confidence": 0.9,
        "confidence_explanation": "e",
    }
    base.update(overrides)
    return PriorRecommendation(**base)


def test_new_unchanged_resolved_suppressed() -> None:
    prior = PriorReport(
        recommendations=[_prior_rec("fp_unchanged"), _prior_rec("fp_resolved", "resolved_concern")],
        evidence_by_id=_evidence(),
    )
    accepted = [_rec("fp_unchanged"), _rec("fp_new", "new_concern")]

    result = compare_with_prior(accepted, prior, _bounds(), ALLOWED, collection_complete=True)

    statuses = {r.fingerprint: r.status for r in result.recommendations}
    assert statuses["fp_unchanged"] == "unchanged"
    assert statuses["fp_new"] == "new"
    assert statuses["fp_resolved"] == "resolved"
    assert result.new_count == 1
    assert result.unchanged_count == 1
    assert result.resolved_count == 1


def test_suppressed_concern_marked_suppressed_not_new() -> None:
    accepted = [_rec("fp_a", "muted_concern")]
    result = compare_with_prior(
        accepted, None, _bounds(frozenset({"muted_concern"})), ALLOWED, collection_complete=True
    )
    assert result.recommendations[0].status == "suppressed"
    assert result.suppressed_count == 1
    assert result.new_count == 0


def test_no_prior_report_everything_is_new() -> None:
    result = compare_with_prior([_rec("fp_a")], None, _bounds(), ALLOWED, collection_complete=True)
    assert result.new_count == 1
    assert result.resolved_count == 0


def test_incomplete_collection_carries_forward_as_unchanged_not_resolved() -> None:
    prior = PriorReport(recommendations=[_prior_rec("fp_missing")], evidence_by_id=_evidence())
    result = compare_with_prior([], prior, _bounds(), ALLOWED, collection_complete=False)
    assert result.recommendations[0].status == "unchanged"
    assert result.resolved_count == 0
    assert result.unchanged_count == 1


def test_invalid_prior_recommendation_is_dropped_not_republished() -> None:
    # category no longer enabled -> fails is_prior_recommendation_valid
    prior = PriorReport(
        recommendations=[_prior_rec("fp_bad", category="not_enabled")], evidence_by_id=_evidence()
    )
    result = compare_with_prior([], prior, _bounds(), ALLOWED, collection_complete=True)
    assert result.recommendations == ()
    assert result.resolved_count == 0


def test_non_string_fingerprint_in_prior_report_is_ignored_not_crashed() -> None:
    prior = PriorReport(
        recommendations=[_prior_rec(["not", "a", "string"])], evidence_by_id=_evidence()
    )
    result = compare_with_prior([], prior, _bounds(), ALLOWED, collection_complete=True)
    assert result.recommendations == ()
    assert result.resolved_count == 0


def test_prior_citing_evidence_absent_from_its_own_report_is_dropped() -> None:
    # A hand-edited prior report could cite evidence it never carried;
    # republishing it would merge a fabricated citation into the new report.
    prior = PriorReport(recommendations=[_prior_rec("fp_ghost")], evidence_by_id={})
    result = compare_with_prior([], prior, _bounds(), ALLOWED, collection_complete=True)
    assert result.recommendations == ()
    assert result.resolved_count == 0


def test_prior_whose_evidence_contradicts_its_concern_rule_is_dropped() -> None:
    rules = {
        "concern": ConcernRule(
            category="security", evidence_kind="k", required_facts={"uses_static_keys": True}
        )
    }
    prior = PriorReport(
        recommendations=[_prior_rec("fp_unsupported")],
        evidence_by_id=_evidence(uses_static_keys=False),
    )
    result = compare_with_prior([], prior, _bounds(), rules, collection_complete=True)
    assert result.recommendations == ()
    assert result.resolved_count == 0


def test_prior_whose_evidence_is_the_wrong_kind_is_dropped() -> None:
    prior = PriorReport(
        recommendations=[_prior_rec("fp_wrong_kind")],
        evidence_by_id=_evidence(kind="a_different_kind"),
    )
    result = compare_with_prior([], prior, _bounds(), ALLOWED, collection_complete=True)
    assert result.recommendations == ()
    assert result.resolved_count == 0


def test_owner_accepted_trade_off_carried_onto_resolved_recommendation() -> None:
    prior = PriorReport(recommendations=[_prior_rec("fp_resolved")], evidence_by_id=_evidence())
    bounds = replace(_bounds(), accepted_trade_offs={"concern": "Owner accepted this."})

    result = compare_with_prior([], prior, bounds, ALLOWED, collection_complete=True)

    assert result.recommendations[0].owner_accepted_trade_off == "Owner accepted this."
