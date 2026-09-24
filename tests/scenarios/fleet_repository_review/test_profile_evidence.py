from infra_fleet_advisor.core.evidence import build_evidence
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_evidence import (
    combine_profiles,
)


def _evidence(path: str, **fact):
    return build_evidence(
        collector_id="c",
        collector_version="1",
        kind="k",
        source_path=path,
        locator="Deployment/apps/web",
        excerpt=f"from {path}",
        fact=fact,
        identity_parts=("Deployment", "apps", "web"),
    )


def test_protective_facts_hold_everywhere_and_risks_count_anywhere() -> None:
    safe = _evidence("base.yaml", guarded=True, risky=False, replicas=2, mode="a")
    unsafe = _evidence("overlay.yaml", guarded=False, risky=True, replicas=2, mode="b")

    [combined] = combine_profiles({"safe": [safe], "open": [unsafe]}, frozenset({"guarded"}))

    assert combined.evidence_id == safe.evidence_id  # identity is stable
    assert combined.fact == {
        "guarded": False,
        "risky": True,
        "replicas": 2,  # agreeing values keep their type
        "mode": "a, b",
        "profiles": "open, safe",
        "failing_profiles": "open",
    }
    # The citation and excerpt describe the failing profile.
    assert combined.source_path == "overlay.yaml"
    assert combined.excerpt.startswith("[open] from overlay.yaml")


def test_objects_present_in_one_profile_are_kept_as_they_are() -> None:
    only = _evidence("base.yaml", guarded=True)

    [combined] = combine_profiles({"local": [only], "aws": []}, frozenset({"guarded"}))

    assert combined.fact["guarded"] is True
    assert combined.fact["failing_profiles"] == ""
