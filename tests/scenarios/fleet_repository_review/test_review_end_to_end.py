import subprocess
from dataclasses import replace
from pathlib import Path

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.review import run_review
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import (
    EvidenceProjection,
    StubSynthesizer,
    SynthesisResponse,
)

POLICY_PATH = Path(__file__).parent.parent.parent / "fixtures" / "policies" / "valid_policy.yaml"
INTENT_PATH = Path(__file__).parent.parent.parent / "fixtures" / "intents"
PRODUCTION_INTENT_PATH = Path(__file__).parents[3] / "intent"
LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


class _EmptySynthesizer:
    model_identifier = "empty-test-analyst"

    def synthesize(self, projection: EvidenceProjection) -> SynthesisResponse:
        assert projection.policy_context.intent_propositions
        return SynthesisResponse((), self.model_identifier)


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


def test_declared_divergence_survives_an_empty_analyst_response(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    policy = load_policy(POLICY_PATH, TAXONOMY)
    catalog = load_intent_catalog(INTENT_PATH, TAXONOMY)
    source = verify_snapshot(repo, sha, "infra-fleet-public")

    report = run_review(
        checkout_root=repo,
        policy=policy,
        source=source,
        synthesizer=_EmptySynthesizer(),
        limits=LIMITS,
        prior=None,
        run_started_at="2026-08-26T00:00:00+00:00",
        intent_catalog=catalog,
    )

    evaluations = {item.proposition_id: item for item in report.intent_evaluations}
    assert report.provenance.intent_digest == catalog.digest
    assert evaluations["T-001"].status == "divergent"
    assert evaluations["S-001"].status == "declared_unverified"
    assert evaluations["S-007"].status == "declared_unverified"
    assert [item.concern_key for item in report.recommendations] == ["trivy_ignore_unfixed"]


def test_authoritative_markdown_drives_the_production_review(git_checkout) -> None:
    repo, sha = git_checkout(
        "static_credentials_bad.yml",
        terraform_files=("wildcard_iam_policy.tf",),
    )
    policy = load_policy(POLICY_PATH, TAXONOMY)
    catalog = load_intent_catalog(PRODUCTION_INTENT_PATH, TAXONOMY)
    source = verify_snapshot(repo, sha, "infra-fleet-public")

    report = run_review(
        checkout_root=repo,
        policy=policy,
        source=source,
        synthesizer=_EmptySynthesizer(),
        limits=LIMITS,
        prior=None,
        run_started_at="2026-08-26T00:00:00+00:00",
        intent_catalog=catalog,
    )

    evaluations = {item.proposition_id: item for item in report.intent_evaluations}
    assert len(evaluations) == 11
    assert evaluations["S-001"].status == "divergent"
    assert evaluations["S-007"].status == "divergent"
    assert {item.status for key, item in evaluations.items() if key not in {"S-001", "S-007"}} == {
        "declared_unverified"
    }
    assert {item.concern_key for item in report.recommendations} == {
        "ci_credentials_without_oidc",
        "wildcard_iam_permissions",
    }


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
        ],
        evidence_by_id={e.evidence_id: e for e in first.evidence},
    )

    # This repo has no Terraform at all — the Terraform collector's "missing
    # infrastructure directory" case reports "ok" with zero evidence rather
    # than "failed", so it doesn't block the GHA finding from resolving.
    clean_repo, clean_sha = git_checkout("oidc_and_trivy_good.yml")
    second = _run(clean_repo, clean_sha, prior=prior)

    assert second.recommendations[0].status == "resolved"
    assert second.resolved_count == 1
    assert all(c.status == "ok" for c in second.coverage)


def test_both_collectors_contribute_to_one_report(git_checkout) -> None:
    repo, sha = git_checkout(
        "trivy_ignore_unfixed_bad.yml", terraform_files=("wildcard_iam_policy.tf",)
    )
    report = _run(repo, sha)

    concern_keys = {r.concern_key for r in report.recommendations}
    assert "trivy_ignore_unfixed" in concern_keys
    assert "wildcard_iam_permissions" in concern_keys
    assert len(report.coverage) == 2
    assert all(c.status == "ok" for c in report.coverage)
    assert len(report.evidence) == 2


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


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)  # noqa: S603


def test_gitignored_workflow_file_is_not_collected_as_evidence(git_checkout) -> None:
    repo, sha = git_checkout("oidc_and_trivy_good.yml")
    (repo / ".gitignore").write_text(".github/workflows/ignored.yml\n", encoding="utf-8")
    _git("git", "add", ".gitignore", cwd=repo)
    _git("git", "commit", "-q", "-m", "add gitignore", cwd=repo)
    sha = subprocess.run(  # fixed argv, test-only
        ["git", "rev-parse", "HEAD"],  # noqa: S603,S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo / ".github" / "workflows" / "ignored.yml").write_text(
        (
            "name: ignored\non: push\njobs:\n  deploy:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: aws-actions/configure-aws-credentials@v4\n"
            "        with:\n          aws-access-key-id: x\n"
        ),
        encoding="utf-8",
    )

    report = _run(repo, sha)

    # oidc_and_trivy_good.yml has no findings; the gitignored file — which
    # WOULD trigger a finding — must never be read as verified evidence.
    assert report.recommendations == ()
    assert report.coverage[0].status == "partial"
    assert "not part of the verified commit" in report.coverage[0].error_summary
