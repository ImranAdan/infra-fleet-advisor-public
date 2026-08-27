from infra_fleet_advisor.core.contracts import PolicyBounds, RawRecommendationCandidate
from infra_fleet_advisor.core.evidence import build_evidence
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.report import RunProvenance, assemble_report

PROVENANCE = RunProvenance(
    source_commit_sha="abc123",
    source_label="infra-fleet-public",
    advisor_version="0.1.0",
    policy_version="1.0",
    collector_versions={"c": "1.0.0"},
    model_identifier="stub-synthesizer-v1",
    run_started_at="2026-08-26T00:00:00+00:00",
)
BOUNDS = PolicyBounds(
    enabled_categories=frozenset({"security"}),
    category_priority={"security": 10},
    max_recommendations=5,
    suppressed_concerns=frozenset(),
)


def test_all_rejected_still_produces_a_report() -> None:
    bad_candidate = RawRecommendationCandidate(
        concern_key="concern",
        category="security",
        priority="not_a_real_priority",
        title="t",
        summary="s",
        evidence_ids=(),
        impact="i",
        suggested_change="c",
        trade_offs="t",
        confidence=0.9,
        confidence_explanation="e",
    )
    report, rejected = assemble_report(
        provenance=PROVENANCE,
        coverage=[],
        candidates=[bad_candidate],
        evidence_by_id={},
        bounds=BOUNDS,
        allowed_concern_keys=frozenset({"concern"}),
        prior=None,
    )
    assert report.recommendations == ()
    assert len(rejected) == 1
    assert report.rejected_count == 1


def test_valid_candidate_flows_through_to_a_ranked_report() -> None:
    ev = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind="k",
        source_path="a.yml",
        locator="loc",
        excerpt="e",
        fact={},
    )
    candidate = RawRecommendationCandidate(
        concern_key="concern",
        category="security",
        priority="high",
        title="t",
        summary="s",
        evidence_ids=(ev.evidence_id,),
        impact="i",
        suggested_change="c",
        trade_offs="t",
        confidence=0.9,
        confidence_explanation="e",
    )
    report, rejected = assemble_report(
        provenance=PROVENANCE,
        coverage=[],
        candidates=[candidate],
        evidence_by_id={ev.evidence_id: ev},
        bounds=BOUNDS,
        allowed_concern_keys=frozenset({"concern"}),
        prior=None,
    )
    assert not rejected
    assert len(report.recommendations) == 1
    assert report.recommendations[0].rank == 1
    assert report.new_count == 1
    assert report.evidence == (ev,)


def test_resolved_recommendation_carries_its_prior_evidence_into_the_report() -> None:
    prior_ev = build_evidence(
        collector_id="c",
        collector_version="1.0.0",
        kind="k",
        source_path="gone.yml",
        locator="loc",
        excerpt="e",
        fact={},
    )
    prior = PriorReport(
        recommendations=[
            PriorRecommendation(
                fingerprint="fp_resolved",
                concern_key="concern",
                category="security",
                priority="high",
                title="t",
                summary="s",
                evidence_ids=(prior_ev.evidence_id,),
                impact="i",
                suggested_change="c",
                trade_offs="t",
                confidence=0.9,
                confidence_explanation="e",
            )
        ],
        evidence_by_id={prior_ev.evidence_id: prior_ev},
    )
    report, _rejected = assemble_report(
        provenance=PROVENANCE,
        coverage=[],
        candidates=[],
        evidence_by_id={},
        bounds=BOUNDS,
        allowed_concern_keys=frozenset({"concern"}),
        prior=prior,
    )
    assert report.recommendations[0].status == "resolved"
    assert report.evidence == (prior_ev,)
