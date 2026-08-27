from collections.abc import Mapping, Sequence

from infra_fleet_advisor.core.contracts import PRIORITIES, Recommendation

_PRIORITY_WEIGHT = {p: w for w, p in enumerate(reversed(PRIORITIES), start=1)}


def rank(
    recommendations: Sequence[Recommendation], category_priority: Mapping[str, int]
) -> tuple[Recommendation, ...]:
    """Only new/unchanged recommendations ask for attention, so only they get
    a rank; resolved/suppressed pass through with rank=None."""
    rankable = [r for r in recommendations if r.status in ("new", "unchanged")]
    other = [r for r in recommendations if r.status not in ("new", "unchanged")]

    def sort_key(rec: Recommendation) -> tuple[int, int, float]:
        return (
            -_PRIORITY_WEIGHT.get(rec.priority, 0),
            -category_priority.get(rec.category, 0),
            -rec.confidence,
        )

    ordered = sorted(rankable, key=sort_key)
    ranked = [
        rec.with_rank(
            i,
            f"priority={rec.priority}, category_weight="
            f"{category_priority.get(rec.category, 0)}, confidence={rec.confidence:.2f}",
        )
        for i, rec in enumerate(ordered, start=1)
    ]
    return tuple(ranked + other)
