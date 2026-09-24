"""Tests for the GitHub Actions workflow evidence collector."""

from dataclasses import replace
from pathlib import Path

import pytest

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
    assert cred_evidence[0].fact["uses_oidc_only"] is False
    assert result.coverage.status == "ok"


def test_detects_oidc_and_safe_trivy_gate(git_checkout) -> None:
    repo, _sha = git_checkout("oidc_and_trivy_good.yml")
    result = gha_collector.collect(repo, LIMITS)
    cred = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_CREDENTIAL_METHOD)
    trivy = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_TRIVY_GATE)
    assert cred.fact["uses_role_to_assume"] is True
    assert cred.fact["uses_static_keys"] is False
    assert cred.fact["has_id_token_write"] is True
    assert cred.fact["force_skip_oidc_disabled"] is True
    assert cred.fact["use_existing_credentials_disabled"] is True
    assert cred.fact["uses_oidc_only"] is True
    assert trivy.fact["ignore_unfixed"] is False


@pytest.mark.parametrize(
    "fixture_name",
    [
        "oidc_missing_permission.yml",
        "oidc_job_permission_override.yml",
        "oidc_force_skip.yml",
        "oidc_use_existing.yml",
    ],
)
def test_oidc_requires_effective_permission_and_no_bypass_inputs(
    git_checkout, fixture_name: str
) -> None:
    repo, _sha = git_checkout(fixture_name)
    result = gha_collector.collect(repo, LIMITS)
    cred = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_CREDENTIAL_METHOD)

    assert cred.fact["uses_oidc_only"] is False


def test_detects_trivy_ignore_unfixed(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    result = gha_collector.collect(repo, LIMITS)
    trivy = next(e for e in result.evidence if e.kind == EVIDENCE_KIND_TRIVY_GATE)
    assert trivy.fact["ignore_unfixed"] is True


def test_evidence_identity_remains_path_sensitive_without_a_stable_step_handle(
    git_checkout,
) -> None:
    first_repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    first = gha_collector.collect(first_repo, LIMITS).evidence[0]

    second_repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    original = second_repo / ".github" / "workflows" / "trivy_ignore_unfixed_bad.yml"
    original.rename(original.with_name("renamed.yml"))
    renamed = gha_collector.collect(second_repo, LIMITS).evidence[0]

    assert first.locator != renamed.locator
    assert first.evidence_id != renamed.evidence_id


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


def test_ineligible_workflows_do_not_consume_the_budget(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    source = repo / ".github/workflows/trivy_ignore_unfixed_bad.yml"
    excluded = source.with_name("aaa-excluded.yml")
    untracked = source.with_name("bbb-untracked.yml")
    excluded.write_text(source.read_text())
    untracked.write_text(source.read_text())
    result = gha_collector.collect(
        repo,
        replace(LIMITS, max_workflow_files=1),
        excluded_paths=frozenset({excluded.relative_to(repo).as_posix()}),
        tracked_paths=frozenset(
            {
                source.relative_to(repo).as_posix(),
                excluded.relative_to(repo).as_posix(),
            }
        ),
    )
    assert any(item.kind == EVIDENCE_KIND_TRIVY_GATE for item in result.evidence)
    assert result.coverage.status == "partial"
    assert "not part of the verified commit" in (result.coverage.error_summary or "")
    assert "omitted" not in (result.coverage.error_summary or "")


def test_tracked_symlink_cannot_read_ignored_workflow_content(git_checkout) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    source = repo / ".github/workflows/trivy_ignore_unfixed_bad.yml"
    ignored = repo / "ignored-workflow.yml"
    source.rename(ignored)
    source.symlink_to(ignored)
    result = gha_collector.collect(
        repo, LIMITS, tracked_paths=frozenset({source.relative_to(repo).as_posix()})
    )
    assert result.evidence == ()
    assert result.coverage.status == "partial"


SCAN = (
    "      - uses: aquasecurity/trivy-action@v0\n"
    "        with:\n          image-ref: app:1\n          severity: CRITICAL,HIGH\n"
    "          exit-code: %s\n"
)
PUSH = "      - run: docker push registry/app:1\n"
LOGIN = "      - uses: aws-actions/amazon-ecr-login@v2\n" + PUSH


def _gate(tmp_path: Path, workflow: str) -> list[bool]:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "publish.yml").write_text(workflow, encoding="utf-8")
    result = gha_collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "ok"
    return [
        bool(item.fact["gated_by_blocking_scan"])
        for item in result.evidence
        if item.kind == "gha_ecr_publication_gate"
    ]


def test_ecr_publication_is_gated_by_a_blocking_scan_through_needs(tmp_path: Path) -> None:
    workflow = (
        "on: push\njobs:\n"
        "  scan:\n    runs-on: x\n    steps:\n"
        + SCAN
        % "1"
        + "  configure:\n    runs-on: x\n    needs: scan\n    steps:\n      - run: echo\n"
        "  push:\n    runs-on: x\n    needs: [configure]\n    steps:\n" + LOGIN
    )

    assert _gate(tmp_path, workflow) == [True]


def test_ecr_publication_gate_rejects_weak_or_bypassed_scans(tmp_path: Path) -> None:
    ungated = {
        "no scan": "  push:\n    runs-on: x\n    steps:\n" + LOGIN,
        "non-blocking exit code": "  push:\n    runs-on: x\n    steps:\n" + SCAN % "0" + LOGIN,
        "scan after login": "  push:\n    runs-on: x\n    steps:\n" + LOGIN + SCAN % "1",
        "status override": (
            "  scan:\n    runs-on: x\n    steps:\n"
            + SCAN % "1"
            + "  push:\n    runs-on: x\n    needs: scan\n    if: always()\n    steps:\n"
            + LOGIN
        ),
        "docker login to ECR": (
            "  push:\n    runs-on: x\n    steps:\n"
            "      - uses: docker/login-action@v3\n        with:\n"
            "          registry: 123456789012.dkr.ecr.eu-west-2.amazonaws.com\n" + PUSH
        ),
        "CLI login": (
            "  push:\n    runs-on: x\n    steps:\n"
            "      - run: aws ecr get-login-password | docker login --password-stdin x\n" + PUSH
        ),
        "filesystem scan": (
            "  push:\n    runs-on: x\n    steps:\n"
            + (SCAN % "1").replace("image-ref: app:1", "scan-type: fs")
            + LOGIN
        ),
        "same-job status override": (
            "  push:\n    runs-on: x\n    steps:\n"
            + SCAN % "1"
            + "      - uses: aws-actions/amazon-ecr-login@v2\n        if: always()\n"
            + PUSH
        ),
    }
    for name, jobs in ungated.items():
        assert _gate(tmp_path, "on: push\njobs:\n" + jobs) == [False], name


def test_scan_earlier_in_the_publishing_job_gates_it(tmp_path: Path) -> None:
    workflow = "on: push\njobs:\n  push:\n    runs-on: x\n    steps:\n" + SCAN % "1" + LOGIN

    assert _gate(tmp_path, workflow) == [True]


def test_ecr_login_without_a_push_is_not_publication(tmp_path: Path) -> None:
    workflow = (
        "on: push\njobs:\n  build:\n    runs-on: x\n    steps:\n"
        "      - uses: aws-actions/amazon-ecr-login@v2\n      - run: docker pull base:1\n"
    )

    assert _gate(tmp_path, workflow) == []


def test_malformed_needs_does_not_crash_the_collector(tmp_path: Path) -> None:
    workflow = "on: push\njobs:\n  push:\n    runs-on: x\n    needs:\n    steps:\n" + LOGIN

    assert _gate(tmp_path, workflow) == [False]


def test_dense_needs_graph_is_evaluated_without_path_explosion(tmp_path: Path) -> None:
    jobs = "".join(
        f"  j{i}:\n    runs-on: x\n    needs: [{', '.join(f'j{k}' for k in range(i))}]\n"
        "    steps:\n      - run: echo\n"
        for i in range(40)
    )
    jobs += "  push:\n    runs-on: x\n    needs: [j39]\n    steps:\n" + LOGIN

    assert _gate(tmp_path, "on: push\njobs:\n" + jobs) == [False]


def _credentials(tmp_path: Path, workflow: str, action: str | None) -> list[dict[str, object]]:
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github" / "workflows" / "apply.yml").write_text(workflow, encoding="utf-8")
    if action is not None:
        (tmp_path / ".github" / "actions" / "aws").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".github" / "actions" / "aws" / "action.yml").write_text(
            action, encoding="utf-8"
        )
    result = gha_collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "ok"
    return [
        {"path": item.source_path, **item.fact}
        for item in result.evidence
        if item.kind == "gha_credential_method"
    ]


COMPOSITE = (
    "runs:\n  using: composite\n  steps:\n"
    "    - uses: aws-actions/configure-aws-credentials@v6\n"
    "      with:\n        role-to-assume: ${{ inputs.role }}\n"
)


def test_credentials_inside_a_local_composite_action_are_evidence(tmp_path: Path) -> None:
    workflow = (
        "on: push\njobs:\n  apply:\n    runs-on: x\n    permissions:\n      id-token: %s\n"
        "    steps:\n      - uses: ./.github/actions/aws\n"
    )

    [granted] = _credentials(tmp_path, workflow % "write", COMPOSITE)
    [withheld] = _credentials(tmp_path, workflow % "none", None)

    assert granted["path"] == ".github/actions/aws/action.yml"
    assert granted["uses_oidc_only"] is True
    assert withheld["uses_oidc_only"] is False


def test_missing_local_action_makes_coverage_partial(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "apply.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: ./.github/actions/gone\n",
        encoding="utf-8",
    )

    assert gha_collector.collect(tmp_path, LIMITS).coverage.status == "partial"


def test_excluded_local_action_is_never_evidence(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "actions" / "aws").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "apply.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: ./.github/actions/aws\n",
        encoding="utf-8",
    )
    (tmp_path / ".github" / "actions" / "aws" / "action.yml").write_text(
        COMPOSITE, encoding="utf-8"
    )

    result = gha_collector.collect(tmp_path, LIMITS, excluded_paths=frozenset({".github/actions"}))

    assert [item for item in result.evidence if item.kind == "gha_credential_method"] == []


CALLER = "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: ./.github/actions/aws\n"


def test_malformed_or_nested_local_actions_make_coverage_partial(tmp_path: Path) -> None:
    for action in (
        "runs:\n  using: composite\n  steps: 1\n",
        "runs:\n  using: composite\n  steps:\n    - uses: ./.github/actions/inner\n",
    ):
        (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".github" / "actions" / "aws").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".github" / "workflows" / "apply.yml").write_text(CALLER, encoding="utf-8")
        (tmp_path / ".github" / "actions" / "aws" / "action.yml").write_text(
            action, encoding="utf-8"
        )

        assert gha_collector.collect(tmp_path, LIMITS).coverage.status == "partial", action


def test_local_action_outside_github_directory_is_followed(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "actions" / "aws").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "apply.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: x\n    permissions:\n      id-token: write\n"
        "    steps:\n      - uses: ./actions/aws\n",
        encoding="utf-8",
    )
    (tmp_path / "actions" / "aws" / "action.yml").write_text(COMPOSITE, encoding="utf-8")

    result = gha_collector.collect(
        tmp_path,
        LIMITS,
        tracked_paths=frozenset({".github/workflows/apply.yml", "actions/aws/action.yml"}),
    )

    assert result.coverage.status == "ok"
    [item] = [e for e in result.evidence if e.kind == "gha_credential_method"]
    assert item.source_path == "actions/aws/action.yml"
