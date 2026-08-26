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
