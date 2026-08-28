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


def test_evidence_identity_survives_a_terraform_file_rename(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    before = tf_collector.collect(repo, LIMITS).evidence[0]

    original = repo / "infrastructure" / "permanent" / "wildcard_iam_policy.tf"
    original.rename(original.with_name("renamed_policy.tf"))
    after = tf_collector.collect(repo, LIMITS).evidence[0]

    assert before.source_path != after.source_path
    assert before.locator == after.locator
    assert before.evidence_id == after.evidence_id


def test_same_resource_address_in_separate_root_modules_has_distinct_identity(
    git_checkout,
) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    original = repo / "infrastructure" / "permanent" / "wildcard_iam_policy.tf"
    second_root = repo / "infrastructure" / "ephemeral"
    second_root.mkdir()
    (second_root / "policy.tf").write_text(original.read_text(encoding="utf-8"), encoding="utf-8")

    evidence = tf_collector.collect(repo, LIMITS).evidence

    assert len(evidence) == 2
    assert evidence[0].locator == evidence[1].locator
    assert evidence[0].evidence_id != evidence[1].evidence_id


def test_root_module_identity_normalizes_platform_path_separators(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    source = repo / "infrastructure" / "permanent" / "wildcard_iam_policy.tf"
    blocks, failures = tf_collector._iter_resource_blocks(source.read_text(encoding="utf-8"))
    resource_type, resource_name, block_body = blocks[0]

    posix, posix_failed = tf_collector._build_resource_evidence(
        "infrastructure/permanent/wildcard_iam_policy.tf",
        resource_type,
        resource_name,
        block_body,
    )
    windows, windows_failed = tf_collector._build_resource_evidence(
        "infrastructure\\permanent\\wildcard_iam_policy.tf",
        resource_type,
        resource_name,
        block_body,
    )

    assert failures == 0
    assert posix_failed is False
    assert windows_failed is False
    assert posix is not None
    assert windows is not None
    assert posix.source_path == windows.source_path
    assert posix.evidence_id == windows.evidence_id


def test_commented_out_wildcard_resource_is_ignored(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("commented_out_wildcard.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_single_statement_object_is_detected(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("single_statement_object.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert len(result.evidence) == 1
    assert "eks:*" in result.evidence[0].fact["wildcard_actions"]


def test_wildcard_statement_count_counts_statements_not_actions(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("multi_action_single_statement.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert "s3:*" in ev.fact["wildcard_actions"]
    assert "ec2:*" in ev.fact["wildcard_actions"]
    # one statement, two wildcard actions -> statement count is 1, not 2
    assert ev.fact["wildcard_statement_count"] == 1


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


def test_missing_infrastructure_dir_is_ok_not_failed(tmp_path) -> None:
    # No Terraform in this repo at all is a legitimate zero-evidence result —
    # it must not permanently block other collectors' findings from ever
    # being marked resolved (collection_complete spans every collector).
    result = tf_collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "ok"
    assert result.evidence == ()


def test_infrastructure_dir_escaping_checkout_is_failed(tmp_path) -> None:
    outside_target = tmp_path / "outside_infra"
    outside_target.mkdir()

    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / "infrastructure").symlink_to(outside_target)

    result = tf_collector.collect(repo, LIMITS)

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
