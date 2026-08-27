from dataclasses import replace
from pathlib import Path

from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.review import run_review
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import StubSynthesizer

POLICY_PATH = Path(__file__).parent.parent.parent / "fixtures" / "policies" / "valid_policy.yaml"
LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def _run(repo: Path, sha: str, prior=None):
    policy = load_policy(POLICY_PATH, TAXONOMY)
    source = verify_snapshot(repo, sha, "infra-fleet-public")
    return run_review(
        checkout_root=repo,
        policy=policy,
        source=source,
        synthesizer=StubSynthesizer(),
        limits=LIMITS,
        prior=prior,
        run_started_at="2026-08-26T00:00:00+00:00",
    )


def test_successful_review_produces_evidence_backed_recommendation(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    report = _run(repo, sha)

    assert len(report.recommendations) == 1
    rec = report.recommendations[0]
    assert rec.status == "new"
    assert rec.evidence_ids
    assert report.coverage[0].status == "ok"


def test_collector_failure_visible_in_coverage(git_checkout) -> None:
    repo, sha = git_checkout()  # no workflow files at all
    report = _run(repo, sha)
    assert report.coverage[0].status == "failed"
    assert report.recommendations == ()


def test_second_run_marks_prior_finding_unchanged(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    first = _run(repo, sha)
    prior = PriorReport(
        recommendations=[
            PriorRecommendation(
                fingerprint=r.fingerprint,
                concern_key=r.concern_key,
                category=r.category,
                priority=r.priority,
                title=r.title,
                summary=r.summary,
                evidence_ids=r.evidence_ids,
                impact=r.impact,
                suggested_change=r.suggested_change,
                trade_offs=r.trade_offs,
                confidence=r.confidence,
                confidence_explanation=r.confidence_explanation,
            )
            for r in first.recommendations
        ]
    )

    second = _run(repo, sha, prior=prior)

    assert second.recommendations[0].status == "unchanged"
    assert second.new_count == 0
    assert second.unchanged_count == 1


def test_third_run_marks_removed_finding_resolved(git_checkout) -> None:
    flagged_repo, flagged_sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    first = _run(flagged_repo, flagged_sha)
    prior = PriorReport(
        recommendations=[
            PriorRecommendation(
                fingerprint=r.fingerprint,
                concern_key=r.concern_key,
                category=r.category,
                priority=r.priority,
                title=r.title,
                summary=r.summary,
                evidence_ids=r.evidence_ids,
                impact=r.impact,
                suggested_change=r.suggested_change,
                trade_offs=r.trade_offs,
                confidence=r.confidence,
                confidence_explanation=r.confidence_explanation,
            )
            for r in first.recommendations
        ]
    )

    clean_repo, clean_sha = git_checkout("oidc_and_trivy_good.yml")
    second = _run(clean_repo, clean_sha, prior=prior)

    assert second.recommendations[0].status == "resolved"
    assert second.resolved_count == 1
    assert second.coverage[0].status == "ok"


def test_evidence_path_exclusions_are_applied(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    policy = replace(
        load_policy(POLICY_PATH, TAXONOMY),
        evidence_path_exclusions=[".github/workflows/trivy_ignore_unfixed_bad.yml"],
    )
    source = verify_snapshot(repo, sha, "infra-fleet-public")

    report = run_review(
        checkout_root=repo,
        policy=policy,
        source=source,
        synthesizer=StubSynthesizer(),
        limits=LIMITS,
        prior=None,
        run_started_at="2026-08-26T00:00:00+00:00",
    )

    assert report.recommendations == ()
