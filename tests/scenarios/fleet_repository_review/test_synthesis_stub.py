from infra_fleet_advisor.core.evidence import build_evidence
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_STATIC_AWS_CREDENTIALS,
    CONCERN_TRIVY_IGNORE_UNFIXED,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_TRIVY_GATE,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import (
    EvidenceProjection,
    PolicyContext,
    StubSynthesizer,
)

CONTEXT = PolicyContext(enabled_categories=frozenset({"security"}), max_recommendations=10)


def test_stub_is_deterministic_and_cites_the_triggering_evidence() -> None:
    ev = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
        source_path="a.yml",
        locator="loc",
        excerpt="e",
        fact={"uses_static_keys": True, "uses_role_to_assume": False},
    )
    projection = EvidenceProjection(policy_context=CONTEXT, evidence=(ev,))

    first = StubSynthesizer().synthesize(projection)
    second = StubSynthesizer().synthesize(projection)

    assert first.recommendations == second.recommendations
    assert first.recommendations[0].concern_key == CONCERN_STATIC_AWS_CREDENTIALS
    assert first.recommendations[0].evidence_ids == (ev.evidence_id,)


def test_stub_ignores_evidence_that_does_not_trigger_a_concern() -> None:
    ev = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind=EVIDENCE_KIND_TRIVY_GATE,
        source_path="a.yml",
        locator="loc",
        excerpt="e",
        fact={"ignore_unfixed": False},
    )
    response = StubSynthesizer().synthesize(
        EvidenceProjection(policy_context=CONTEXT, evidence=(ev,))
    )
    assert response.recommendations == ()


def test_stub_emits_one_candidate_per_triggering_item() -> None:
    ev1 = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind=EVIDENCE_KIND_TRIVY_GATE,
        source_path="a.yml",
        locator="loc1",
        excerpt="e",
        fact={"ignore_unfixed": True},
    )
    ev2 = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind=EVIDENCE_KIND_TRIVY_GATE,
        source_path="b.yml",
        locator="loc2",
        excerpt="e",
        fact={"ignore_unfixed": True},
    )
    response = StubSynthesizer().synthesize(
        EvidenceProjection(policy_context=CONTEXT, evidence=(ev1, ev2))
    )
    assert len(response.recommendations) == 2
    assert all(r.concern_key == CONCERN_TRIVY_IGNORE_UNFIXED for r in response.recommendations)
