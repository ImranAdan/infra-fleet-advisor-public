from infra_fleet_advisor.core.contracts import compute_fingerprint


def test_fingerprint_stable_regardless_of_evidence_order() -> None:
    a = compute_fingerprint("security", "concern", ["e1", "e2"])
    b = compute_fingerprint("security", "concern", ["e2", "e1"])
    assert a == b


def test_fingerprint_ignores_narrative_text_by_construction() -> None:
    # Narrative text isn't even a parameter — same inputs always fingerprint
    # identically no matter how a (future) model rewords its output.
    a = compute_fingerprint("security", "concern", ["e1"])
    b = compute_fingerprint("security", "concern", ["e1"])
    assert a == b


def test_fingerprint_differs_by_category_or_concern() -> None:
    base = compute_fingerprint("security", "concern", ["e1"])
    assert compute_fingerprint("reliability", "concern", ["e1"]) != base
    assert compute_fingerprint("security", "other_concern", ["e1"]) != base
