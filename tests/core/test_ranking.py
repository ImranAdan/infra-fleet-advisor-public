from infra_fleet_advisor.core.contracts import Recommendation
from infra_fleet_advisor.core.ranking import rank


def _rec(priority: str, category: str, confidence: float, status: str = "new") -> Recommendation:
    return Recommendation(
        fingerprint=f"fp_{priority}_{category}_{confidence}",
        concern_key="c",
        category=category,
        priority=priority,
        title="t",
        summary="s",
        evidence_ids=("e1",),
        impact="i",
        suggested_change="x",
        trade_offs="t",
        confidence=confidence,
        confidence_explanation="e",
        status=status,
    )


def test_ranks_by_priority_then_category_weight_then_confidence() -> None:
    low = _rec("low", "security", 0.9)
    high = _rec("high", "security", 0.5)
    critical = _rec("critical", "reliability", 0.1)

    ranked = rank([low, high, critical], category_priority={"security": 10, "reliability": 1})

    assert [r.fingerprint for r in ranked] == [
        critical.fingerprint,
        high.fingerprint,
        low.fingerprint,
    ]
    assert ranked[0].rank == 1


def test_resolved_and_suppressed_get_no_rank() -> None:
    resolved = _rec("high", "security", 0.9, status="resolved")
    ranked = rank([resolved], category_priority={})
    assert ranked[0].rank is None
