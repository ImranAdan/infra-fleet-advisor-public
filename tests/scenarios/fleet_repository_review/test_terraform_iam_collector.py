from dataclasses import replace
from pathlib import Path

import pytest

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


def test_local_condition_traversal_does_not_hide_literal_wildcard_grant(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        """resource "aws_iam_policy" "controller" {
          policy = jsonencode({
            Statement = [{
              Effect = "Allow"
              Action = "eks:*"
              Resource = "*"
              Condition = local.region_only
            }]
          })
        }""",
    )

    assert result.coverage.status == "ok"
    assert result.evidence[0].fact["wildcard_actions"] == "eks:*"


def test_fixed_prefix_resource_interpolation_is_known_not_to_equal_wildcard(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        """resource "aws_iam_policy" "controller" {
          policy = jsonencode({
            Statement = [{
              Effect = "Allow"
              Action = "ecr:GetDownloadUrlForLayer"
              Resource = "arn:aws:ecr:${local.region}:${local.account}:repository/app"
            }]
          })
        }""",
    )

    assert result.coverage.status == "ok"
    assert result.evidence == ()


@pytest.mark.parametrize("field", ["Action", "Resource"])
def test_interpolation_only_decision_fields_remain_incomplete(tmp_path, field) -> None:
    result = _collect_text(
        tmp_path,
        'resource "aws_iam_policy" "controller" {\n'
        ' policy = jsonencode({ Statement = [{ Effect = "Allow", '
        f'{field} = "${{local.value}}", '
        f'{"Resource" if field == "Action" else "Action"} = "*" }}] }})\n}}',
    )

    assert result.evidence == ()
    assert result.coverage.status == "partial"


def test_collection_scope_excludes_unparseable_policy_outside_persistent_stack(tmp_path) -> None:
    permanent = tmp_path / "infrastructure/permanent/policy.tf"
    permanent.parent.mkdir(parents=True)
    permanent.write_text(
        'resource "aws_iam_policy" "persistent" {\n'
        ' policy = jsonencode({ Statement = [{ Effect = "Allow", '
        'Action = "iam:GetRole", Resource = "*" }] })\n}\n',
        encoding="utf-8",
    )
    staging = tmp_path / "infrastructure/staging/policy.tf"
    staging.parent.mkdir(parents=True)
    staging.write_text(
        'resource "aws_iam_policy" "external" { policy = data.http.policy.response_body }\n',
        encoding="utf-8",
    )

    result = tf_collector.collect(
        tmp_path,
        LIMITS,
        tracked_paths=frozenset({permanent.relative_to(tmp_path).as_posix()}),
        included_path_prefixes=("infrastructure/permanent",),
    )

    assert result.coverage.status == "ok"
    assert result.evidence == ()


def test_non_iam_resource_produces_no_evidence_or_failure(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("non_iam_resource.tf",))
    result = tf_collector.collect(repo, LIMITS)
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_missing_infrastructure_dir_is_ok_not_failed(tmp_path) -> None:
    # No Terraform in this repo at all is a legitimate zero-evidence result —
    # it records complete Terraform coverage without inventing evidence.
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


def test_downloaded_modules_do_not_displace_verified_policy(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    source = repo / "infrastructure/permanent/wildcard_iam_policy.tf"
    cache = repo / "infrastructure/permanent/.terraform/modules/downloaded"
    cache.mkdir(parents=True)
    for number in range(60):
        (cache / f"module-{number}.tf").write_text(source.read_text())
    result = tf_collector.collect(
        repo,
        replace(LIMITS, max_workflow_files=1),
        tracked_paths=frozenset({source.relative_to(repo).as_posix()}),
    )
    assert len(result.evidence) == 1
    assert result.coverage.status == "ok"
    assert result.coverage.error_summary is None


def test_ineligible_terraform_files_do_not_consume_the_budget(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    source = repo / "infrastructure/permanent/wildcard_iam_policy.tf"
    excluded = source.with_name("aaa-excluded.tf")
    untracked = source.with_name("bbb-untracked.tf")
    excluded.write_text(source.read_text())
    untracked.write_text(source.read_text())
    result = tf_collector.collect(
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
    assert len(result.evidence) == 1
    assert result.coverage.status == "partial"
    assert "not part of the verified commit" in (result.coverage.error_summary or "")
    assert "omitted" not in (result.coverage.error_summary or "")


def _collect_text(tmp_path: Path, text: str) -> tf_collector.CollectorResult:
    source = tmp_path / "infrastructure/permanent/policy.tf"
    source.parent.mkdir(parents=True)
    source.write_text(text, encoding="utf-8")
    return tf_collector.collect(tmp_path, LIMITS)


@pytest.mark.parametrize(
    "expression",
    [
        "data.http.controller_policy.response_body",
        "data.aws_iam_policy_document.controller.json",
        "local.policy",
        'file("policy.json")',
        "jsonencode(local.policy)",
        'jsonencode({ Statement = [] }) + "extra"',
        'jsonencode({ Statement = [] })\n+ "extra"',
    ],
)
def test_referenced_or_dynamic_policies_report_incomplete_coverage(tmp_path, expression) -> None:
    result = _collect_text(
        tmp_path, f'resource "aws_iam_policy" "controller" {{\n policy = {expression}\n}}'
    )
    assert result.evidence == ()
    assert result.coverage.status == "partial"
    assert "unparseable" in (result.coverage.error_summary or "")


@pytest.mark.parametrize(
    "statement",
    [
        "null",
        '"not a statement"',
        '{ Effect = ["Allow"], Action = "eks:*", Resource = "*" }',
        '{ Effect = local.effect, Action = "eks:*", Resource = "*" }',
        '{ Effect = "Allow", Action = null, Resource = "*" }',
        '{ Effect = "Allow", Action = [], Resource = "*" }',
        '{ Effect = "Allow", Action = local.actions, Resource = "*" }',
        '{ Effect = "Allow", Action = "eks:*", Resource = {} }',
        '{ Effect = "Allow", Action = "eks:*", Resource = "" }',
        '{ Effect = "Allow", Action = "eks:*", Resource = local.resource }',
        '{ Effect = "Allow", NotAction = "eks:Describe*", Resource = "*" }',
    ],
)
def test_unsupported_statement_shapes_fail_closed_without_crashing(tmp_path, statement) -> None:
    result = _collect_text(
        tmp_path,
        'resource "aws_iam_policy" "controller" {\n'
        f" policy = jsonencode({{ Statement = [{statement}] }})\n}}",
    )
    assert result.evidence == ()
    assert result.coverage.status == "partial"


@pytest.mark.parametrize(
    "policy",
    [
        '{ "Statement" = [{ "Effect" = "Allow", "Action" = "eks:*", "Resource" = "*" }] }',
        '{ "Statement": [{ "Effect": "Allow", "Action": ["eks:*"], "Resource": "*" }] }',
        """{
          Statement = [{
            Effect = "Allow"
            Action = ["eks:*",]
            Resource = "*"
            Condition = { StringEquals = { "aws:RequestedRegion" = "eu-west-2" } }
          },]
        }""",
    ],
)
def test_quoted_hcl_keys_and_json_literals_are_supported(tmp_path, policy) -> None:
    result = _collect_text(
        tmp_path, f'resource "aws_iam_policy" "controller" {{\n policy = jsonencode({policy})\n}}'
    )
    assert result.coverage.status == "ok"
    assert len(result.evidence) == 1
    assert result.evidence[0].fact["wildcard_actions"] == "eks:*"


def test_comment_and_delimiter_text_in_strings_does_not_hide_a_grant(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        """resource "aws_iam_policy" "controller" {
          description = "https://example.invalid/# /* } ) { literal */"
          policy = jsonencode({
            # } ) resource "aws_iam_policy" "fake" {
            Statement = [{
              Sid = "https://example.invalid/# /* } ) { literal */"
              Effect = "Allow" // } )
              Action = "eks:*" /* } ) */
              Resource = "*"
            }]
          })
        }""",
    )
    assert result.coverage.status == "ok"
    assert len(result.evidence) == 1


@pytest.mark.parametrize("prefix", ["#", "//"])
def test_line_commented_resource_is_not_active_configuration(tmp_path, prefix) -> None:
    result = _collect_text(
        tmp_path,
        f'{prefix} resource "aws_iam_policy" "retired" {{\n'
        f'{prefix} policy = jsonencode({{ Statement = [{{ Effect = "Allow",'
        ' Action = "eks:*", Resource = "*" }] })\n'
        f"{prefix} }}\n",
    )
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_resource_and_policy_examples_in_heredocs_are_inert(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        """locals {
          documentation = <<-EXAMPLE
            resource "aws_iam_policy" "example" {
              policy = jsonencode({ Statement = [{
                Effect = "Allow", Action = "eks:*", Resource = "*"
              }] })
            }
          EXAMPLE
        }
        """,
    )
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_nested_policy_attribute_cannot_replace_the_resource_policy(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        """resource "aws_iam_policy" "controller" {
          policy = local.actual_policy
          tags = {
            policy = jsonencode({ Statement = [{
              Effect = "Allow", Action = "eks:*", Resource = "*"
            }] })
          }
        }""",
    )
    assert result.evidence == ()
    assert result.coverage.status == "partial"


@pytest.mark.parametrize(
    "policy",
    [
        '{ Statement = [{ Effect = "Allow", Action = "${var.action}", Resource = "*" }] }',
        '{ Statement = [{ Effect = "Allow", Action = "eks:*", Resource = "*" }], Statement = [] }',
        "{ Statement = [] }",
        '{ Statement = [{ Effect = "Allow", Action = "eks:*", Resource = "*" }],'
        " Metadata = " + "[" * 70 + "0" + "]" * 70 + " }",
    ],
)
def test_ambiguous_dynamic_and_deep_literals_are_incomplete(tmp_path, policy) -> None:
    result = _collect_text(
        tmp_path, f'resource "aws_iam_policy" "controller" {{\n policy = jsonencode({policy})\n}}'
    )
    assert result.evidence == ()
    assert result.coverage.status == "partial"


_FLEET_SHAPE = """
data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "ci" {
  name = "ci"
  assume_role_policy = jsonencode({
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRoleWithWebIdentity" }]
  })
}

resource "aws_iam_policy" "ci" {
  policy = jsonencode({
    Statement = [{ Effect = "Allow", Action = ["ec2:Describe*"], Resource = "*" }]
  })
  depends_on = [aws_iam_role_policy_attachment.ci]
}

resource "aws_iam_role_policy_attachment" "ci" {
  role       = aws_iam_role.ci.name
  policy_arn = aws_iam_policy.ci.arn
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = "app"
  policy     = jsonencode({ rules = [] })
}
"""


def test_complete_persistent_iam_is_fully_accounted_for(tmp_path) -> None:
    result = _collect_text(tmp_path, _FLEET_SHAPE)

    assert result.coverage.status == "ok"
    assert result.evidence == ()


def test_service_wide_wildcard_on_a_scoped_resource_is_still_a_grant(tmp_path) -> None:
    result = _collect_text(
        tmp_path,
        'resource "aws_iam_role_policy" "ci" {\n policy = jsonencode({ Statement = [{'
        ' Effect = "Allow", Action = ["eks:*", "ec2:Describe*", "*:Get*"],'
        ' Resource = "arn:aws:eks:eu-west-2:1:cluster/x" }] })\n}',
    )

    assert result.coverage.status == "ok"
    assert result.evidence[0].fact["wildcard_actions"] == "eks:*, *:Get*"


_DOCUMENT = """
data "aws_iam_policy_document" "ci" {
  statement {
    sid       = "Read"
    actions   = [ACTIONS]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["eu-west-2"]
    }
  }
  statement {
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "ci" {
  policy = data.aws_iam_policy_document.ci.json
}
"""


def test_literal_policy_document_is_parsed_and_referenced(tmp_path) -> None:
    result = _collect_text(tmp_path, _DOCUMENT.replace("ACTIONS", '"ec2:DescribeVpcs"'))

    assert result.coverage.status == "ok"
    assert result.evidence == ()


def test_wildcard_in_policy_document_is_evidence_on_the_document(tmp_path) -> None:
    result = _collect_text(tmp_path, _DOCUMENT.replace("ACTIONS", '"s3:*"'))

    assert result.coverage.status == "ok"
    [item] = result.evidence
    assert item.locator == "data.aws_iam_policy_document.ci"
    assert item.fact["wildcard_actions"] == "s3:*"


@pytest.mark.parametrize(
    ("find", "replace"),
    [
        # An AWS-managed or external policy's contents are unknown.
        ("aws_iam_policy.ci.arn", '"arn:aws:iam::aws:policy/ReadOnlyAccess"'),
        ("aws_iam_policy.ci.arn", "aws_iam_policy.elsewhere.arn"),
        ("aws_iam_policy.ci.arn", "var.policy_arn"),
        ('name = "ci"', 'name = "ci"\n  managed_policy_arns = [var.arn]'),
        ('name = "ci"', 'name = "ci"\n  inline_policy {\n    policy = var.p\n  }'),
        ('name = "ci"', 'name = "ci"\n  dynamic "inline_policy" {\n    for_each = []\n  }'),
        ('Action = ["ec2:Describe*"]', 'Action = ["ec2:${var.action}"]'),
        ('data "aws_caller_identity" "current" {}', 'module "iam" {\n  source = "./iam"\n}'),
        (
            'data "aws_caller_identity" "current" {}',
            'resource "aws_iam_user" "bot" {\n  name = "bot"\n}',
        ),
        (
            'data "aws_caller_identity" "current" {}',
            'data "aws_iam_policy" "admin" {\n  name = "AdministratorAccess"\n}',
        ),
        ("aws_ecr_lifecycle_policy", "aws_ecr_repository_policy"),
        (
            'data "aws_caller_identity" "current" {}',
            'resource "aws_kms_key" "k" {\n  dynamic "policy" {\n    for_each = []\n  }\n}',
        ),
        # The same address declared twice cannot be resolved to one policy.
        ('resource "aws_iam_role" "ci"', 'resource "aws_iam_policy" "ci"'),
    ],
)
def test_iam_the_collector_cannot_read_leaves_coverage_partial(tmp_path, find, replace) -> None:
    assert find in _FLEET_SHAPE
    result = _collect_text(tmp_path, _FLEET_SHAPE.replace(find, replace))

    assert result.evidence == ()
    assert result.coverage.status == "partial"


@pytest.mark.parametrize(
    ("find", "replace"),
    [
        ('sid       = "Read"', 'not_actions = ["s3:*"]'),
        ("statement {\n    effect", 'dynamic "statement" {\n    effect'),
        (
            'sid       = "Read"',
            'sid = "Read"\n    not_principals {\n      type = "*"\n    }\n    other {\n    }',
        ),
        ("data.aws_iam_policy_document.ci.json", "data.aws_iam_policy_document.other.json"),
        (
            "statement {\n    effect",
            "source_policy_documents = [var.doc]\n  statement {\n    effect",
        ),
        ('effect    = "Deny"', "effect = var.effect"),
    ],
)
def test_policy_documents_the_collector_cannot_read_leave_coverage_partial(
    tmp_path, find, replace
) -> None:
    text = _DOCUMENT.replace("ACTIONS", '"ec2:DescribeVpcs"')
    assert find in text
    result = _collect_text(tmp_path, text.replace(find, replace))

    assert result.coverage.status == "partial"


@pytest.mark.parametrize("name", ["iam.tf.json", "override.tf", "iam_override.tf"])
def test_json_and_override_files_leave_coverage_partial(tmp_path, name) -> None:
    root = tmp_path / "infrastructure/permanent"
    root.mkdir(parents=True)
    (root / "main.tf").write_text(_FLEET_SHAPE, encoding="utf-8")
    (root / name).write_text("{}", encoding="utf-8")

    result = tf_collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"


def test_policy_excluded_file_leaves_coverage_partial(git_checkout) -> None:
    repo, _sha = git_checkout(terraform_files=("scoped_iam_policy.tf",))
    excluded = frozenset({"infrastructure/permanent/scoped_iam_policy.tf"})

    result = tf_collector.collect(repo, LIMITS, excluded_paths=excluded)

    assert result.coverage.status == "partial"


def test_missing_declared_scope_is_failed(tmp_path) -> None:
    result = tf_collector.collect(
        tmp_path, LIMITS, included_path_prefixes=("infrastructure/permanent",)
    )

    assert result.coverage.status == "failed"
