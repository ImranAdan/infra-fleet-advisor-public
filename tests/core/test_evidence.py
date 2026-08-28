from infra_fleet_advisor.core.evidence import assign_evidence_id, build_evidence


def test_evidence_id_deterministic() -> None:
    a = assign_evidence_id("collector", "path.yml", "jobs.x.steps[0]")
    b = assign_evidence_id("collector", "path.yml", "jobs.x.steps[0]")
    assert a == b
    assert a.startswith("collector:")


def test_evidence_id_differs_by_locator() -> None:
    a = assign_evidence_id("collector", "path.yml", "jobs.x.steps[0]")
    b = assign_evidence_id("collector", "path.yml", "jobs.x.steps[1]")
    assert a != b


def test_evidence_id_structurally_encodes_delimiter_characters() -> None:
    first = assign_evidence_id("collector", "a|b", "c")
    second = assign_evidence_id("collector", "a", "b|c")

    assert first != second


def test_evidence_id_requires_an_identity_part() -> None:
    try:
        assign_evidence_id("collector")
    except ValueError as exc:
        assert str(exc) == "evidence identity must have at least one part"
    else:
        raise AssertionError("empty evidence identity was accepted")


def test_build_evidence_normalizes_path_and_truncates_excerpt() -> None:
    ev = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind="k",
        source_path="a/./b.yml",
        locator="loc",
        excerpt="x" * 500,
        fact={"flag": True},
    )
    assert ev.source_path == "a/b.yml"
    assert len(ev.excerpt) == 280


def test_build_evidence_can_use_a_path_independent_identity() -> None:
    common = {
        "collector_id": "c",
        "collector_version": "1.0.0",
        "kind": "k",
        "locator": "resource.aws_iam_policy.example.policy",
        "excerpt": "wildcard policy",
        "fact": {"flag": True},
        "identity_parts": ("resource.aws_iam_policy.example.policy",),
    }

    before = build_evidence(source_path="old/policy.tf", **common)
    after = build_evidence(source_path="new/policy.tf", **common)

    assert before.evidence_id == after.evidence_id
