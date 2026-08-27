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


def test_detects_unquoted_yaml_bool_for_ignore_unfixed(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_unquoted.yml")
    result = gha_collector.collect(repo, LIMITS)
    trivy = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_TRIVY_GATE)
    assert trivy.fact["ignore_unfixed"] is True


def test_similarly_named_action_is_not_misattributed(git_checkout) -> None:
    repo, _sha = git_checkout("similarly_named_action.yml")
    result = gha_collector.collect(repo, LIMITS)
    assert result.evidence == ()


def test_symlink_escaping_checkout_root_is_not_read(tmp_path) -> None:
    outside_target = tmp_path / "outside.yml"
    outside_target.write_text("secret: content\n", encoding="utf-8")

    repo = tmp_path / "checkout"
    workflows_dir = repo / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "escape.yml").symlink_to(outside_target)

    result = gha_collector.collect(repo, LIMITS)

    assert result.evidence == ()
    assert result.coverage.status == "partial"


def test_excluded_paths_are_skipped(git_checkout) -> None:
    repo, _sha = git_checkout("static_credentials_bad.yml", "trivy_ignore_unfixed_bad.yml")
    excluded = frozenset({".github/workflows/static_credentials_bad.yml"})

    result = gha_collector.collect(repo, LIMITS, excluded_paths=excluded)

    assert all(e.kind != EVIDENCE_KIND_CREDENTIAL_METHOD for e in result.evidence)
    assert any(e.kind == EVIDENCE_KIND_TRIVY_GATE for e in result.evidence)


def test_truncation_beyond_max_workflow_files_reported_as_partial(git_checkout) -> None:
    repo, _sha = git_checkout("static_credentials_bad.yml", "trivy_ignore_unfixed_bad.yml")
    limits = ExecutionLimits(
        max_wall_seconds=60,
        max_model_calls=1,
        max_workflow_files=1,
        max_file_bytes=256 * 1024,
        max_recommendations=10,
    )

    result = gha_collector.collect(repo, limits)

    assert result.coverage.status == "partial"
    assert "omitted" in result.coverage.error_summary


def test_untracked_file_not_in_tracked_paths_is_skipped(git_checkout) -> None:
    repo, _sha = git_checkout("static_credentials_bad.yml", "trivy_ignore_unfixed_bad.yml")
    # Simulate a .gitignore'd file present on disk but not part of HEAD: only
    # one of the two committed files is listed as "tracked".
    tracked = frozenset({".github/workflows/trivy_ignore_unfixed_bad.yml"})

    result = gha_collector.collect(repo, LIMITS, tracked_paths=tracked)

    assert all(e.kind != EVIDENCE_KIND_CREDENTIAL_METHOD for e in result.evidence)
    assert any(e.kind == EVIDENCE_KIND_TRIVY_GATE for e in result.evidence)
    assert result.coverage.status == "partial"
    assert "not part of the verified commit" in result.coverage.error_summary


def test_tracked_paths_none_skips_the_check(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    result = gha_collector.collect(repo, LIMITS, tracked_paths=None)
    assert result.coverage.status == "ok"
