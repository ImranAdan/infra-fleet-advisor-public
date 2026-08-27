from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    terraform_iam_collector as tf_collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_IAM_WILDCARD,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def test_detects_wildcard_iam_policy(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    result = tf_collector.collect(repo, LIMITS)

    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.kind == EVIDENCE_KIND_IAM_WILDCARD
    assert "eks:*" in ev.fact["wildcard_actions"]
    assert "ec2:*" in ev.fact["wildcard_actions"]
    assert ev.fact["wildcard_statement_count"] == 2
    assert result.coverage.status == "ok"


def test_scoped_policy_produces_no_evidence(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("scoped_iam_policy.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_non_iam_resource_produces_no_evidence_or_failure(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("non_iam_resource.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_missing_infrastructure_dir(tmp_path) -> None:
    result = tf_collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "failed"
    assert result.evidence == ()


def test_malformed_resource_reported_as_partial_not_a_crash(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("malformed.tf", "wildcard_iam_policy.tf"))
    result = tf_collector.collect(repo, LIMITS)
    assert result.coverage.status == "partial"
    assert result.coverage.error_summary is not None
    # the one good file still contributes evidence
    assert result.evidence


def test_symlink_escaping_checkout_root_is_not_read(tmp_path) -> None:
    outside_target = tmp_path / "outside.tf"
    outside_target.write_text('resource "aws_iam_policy" "x" {}\n', encoding="utf-8")

    repo = tmp_path / "checkout"
    infra_dir = repo / "infrastructure"
    infra_dir.mkdir(parents=True)
    (infra_dir / "escape.tf").symlink_to(outside_target)

    result = tf_collector.collect(repo, LIMITS)

    assert result.evidence == ()
    assert result.coverage.status == "partial"


def test_excluded_paths_are_skipped(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    excluded = frozenset({"infrastructure/permanent/wildcard_iam_policy.tf"})

    result = tf_collector.collect(repo, LIMITS, excluded_paths=excluded)

    assert result.evidence == ()


def test_truncation_beyond_max_workflow_files_reported_as_partial(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf", "scoped_iam_policy.tf"))
    limits = ExecutionLimits(
        max_wall_seconds=60,
        max_model_calls=1,
        max_workflow_files=1,
        max_file_bytes=256 * 1024,
        max_recommendations=10,
    )

    result = tf_collector.collect(repo, limits)

    assert result.coverage.status == "partial"
    assert "omitted" in result.coverage.error_summary


def test_untracked_file_not_in_tracked_paths_is_skipped(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf", "scoped_iam_policy.tf"))
    tracked = frozenset({"infrastructure/permanent/scoped_iam_policy.tf"})

    result = tf_collector.collect(repo, LIMITS, tracked_paths=tracked)

    assert result.evidence == ()
    assert result.coverage.status == "partial"
    assert "not part of the verified commit" in result.coverage.error_summary


def test_tracked_paths_none_skips_the_check(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    result = tf_collector.collect(repo, LIMITS, tracked_paths=None)
    assert result.coverage.status == "ok"
