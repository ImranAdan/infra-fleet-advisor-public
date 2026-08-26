from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    github_actions_workflow_collector as gha_collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_TRIVY_GATE,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def test_detects_static_credentials(git_checkout) -> None:
    repo, _sha = git_checkout("static_credentials_bad.yml")
    result = gha_collector.collect(repo, LIMITS)
    cred_evidence = [e for e in result.evidence if e.kind == EVIDENCE_KIND_CREDENTIAL_METHOD]
    assert len(cred_evidence) == 1
    assert cred_evidence[0].fact["uses_static_keys"] is True
    assert result.coverage.status == "ok"


def test_detects_oidc_and_safe_trivy_gate(git_checkout) -> None:
    repo, _sha = git_checkout("oidc_and_trivy_good.yml")
    result = gha_collector.collect(repo, LIMITS)
    cred = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_CREDENTIAL_METHOD)
    trivy = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_TRIVY_GATE)
    assert cred.fact["uses_role_to_assume"] is True
    assert cred.fact["uses_static_keys"] is False
    assert trivy.fact["ignore_unfixed"] is False


def test_detects_trivy_ignore_unfixed(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    result = gha_collector.collect(repo, LIMITS)
    trivy = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_TRIVY_GATE)
    assert trivy.fact["ignore_unfixed"] is True


def test_missing_workflows_dir(tmp_path) -> None:
    result = gha_collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "failed"
    assert result.evidence == ()


def test_malformed_yaml_reported_as_partial_not_a_crash(git_checkout) -> None:
    repo, _sha = git_checkout("malformed.yml", "oidc_and_trivy_good.yml")
    result = gha_collector.collect(repo, LIMITS)
    assert result.coverage.status == "partial"
    assert result.coverage.error_summary is not None
    # the one good file still contributes evidence
    assert result.evidence
