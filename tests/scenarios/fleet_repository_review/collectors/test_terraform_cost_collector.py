from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    terraform_cost_collector as collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_ECR_LIFECYCLE,
    EVIDENCE_KIND_LOG_RETENTION,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)

EKS = """
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.25.0"
%s
}
"""

BOUNDED_POLICY = """
resource "aws_ecr_repository" "app" {
  name = "app"
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = %s

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        selection = {
          tagStatus   = "%s"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}
"""


def _collect(tmp_path: Path, files: dict[str, str]) -> collector.CollectorResult:
    for rel_path, text in files.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return collector.collect(tmp_path, LIMITS)


def _facts(result: collector.CollectorResult, kind: str) -> list[dict[str, object]]:
    return [dict(item.fact) for item in result.evidence if item.kind == kind]


def test_log_group_retention_is_bounded_only_between_one_and_thirty_days(tmp_path) -> None:
    cases = {"": 0, "retention_in_days = 14": 14, "retention_in_days = 90": 90}
    for attribute, days in cases.items():
        result = _collect(
            tmp_path,
            {
                "infrastructure/staging/logs.tf": (
                    f'resource "aws_cloudwatch_log_group" "app" {{\n  {attribute}\n}}\n'
                )
            },
        )
        assert result.coverage.status == "ok"
        assert _facts(result, EVIDENCE_KIND_LOG_RETENTION) == [
            {"retention_days": days, "bounded_retention": days == 14}
        ]


def test_variable_retention_is_partial_not_assumed(tmp_path) -> None:
    result = _collect(
        tmp_path,
        {
            "infrastructure/staging/logs.tf": (
                'resource "aws_cloudwatch_log_group" "app" {\n  retention_in_days = var.days\n}\n'
            )
        },
    )

    assert result.coverage.status == "partial"
    assert result.evidence == ()


def test_eks_module_uses_trusted_log_group_defaults(tmp_path) -> None:
    cases = {
        "": [{"retention_days": 90, "bounded_retention": False}],
        "  cloudwatch_log_group_retention_in_days = 14": [
            {"retention_days": 14, "bounded_retention": True}
        ],
        "  create_cloudwatch_log_group = false": [
            {"retention_days": 0, "bounded_retention": False}
        ],
        "  enabled_log_types = []": [],
    }
    for settings, expected in cases.items():
        result = _collect(tmp_path, {"infrastructure/staging/eks.tf": EKS % settings})
        assert result.coverage.status == "ok"
        assert _facts(result, EVIDENCE_KIND_LOG_RETENTION) == expected


def test_untrusted_eks_module_major_is_partial(tmp_path) -> None:
    text = (EKS % "").replace("21.25.0", "22.0.0")

    result = _collect(tmp_path, {"infrastructure/staging/eks.tf": text})

    assert result.coverage.status == "partial"
    assert result.evidence == ()


def test_modules_declared_in_strings_or_comments_are_ignored(tmp_path) -> None:
    text = '# module "eks" {\nlocals {\n  x = "module \\"eks\\" {"\n}\n'

    result = _collect(tmp_path, {"infrastructure/staging/main.tf": text})

    assert result.coverage.status == "ok"
    assert result.evidence == ()


def test_ecr_lifecycle_policy_is_joined_by_reference_or_literal_name(tmp_path) -> None:
    for reference in ("aws_ecr_repository.app.name", '"app"'):
        result = _collect(
            tmp_path, {"infrastructure/permanent/ecr.tf": BOUNDED_POLICY % (reference, "any")}
        )
        assert result.coverage.status == "ok"
        assert _facts(result, EVIDENCE_KIND_ECR_LIFECYCLE) == [
            {
                "has_lifecycle_policy": True,
                "expires_untagged": True,
                "bounds_retained_images": True,
                "bounded_lifecycle": True,
            }
        ]


def test_ecr_policy_limited_to_untagged_images_does_not_bound_retention(tmp_path) -> None:
    result = _collect(
        tmp_path,
        {
            "infrastructure/permanent/ecr.tf": BOUNDED_POLICY
            % ("aws_ecr_repository.app.name", "untagged")
        },
    )

    [fact] = _facts(result, EVIDENCE_KIND_ECR_LIFECYCLE)
    assert fact["expires_untagged"] is True
    assert fact["bounded_lifecycle"] is False


def test_ecr_repository_without_policy_is_unbounded(tmp_path) -> None:
    result = _collect(
        tmp_path, {"infrastructure/permanent/ecr.tf": 'resource "aws_ecr_repository" "app" {\n}\n'}
    )

    assert result.coverage.status == "ok"
    [fact] = _facts(result, EVIDENCE_KIND_ECR_LIFECYCLE)
    assert fact["has_lifecycle_policy"] is False
    assert fact["bounded_lifecycle"] is False


def test_unresolved_ecr_policy_is_partial(tmp_path) -> None:
    result = _collect(
        tmp_path,
        {"infrastructure/permanent/ecr.tf": BOUNDED_POLICY % ("var.repository", "any")},
    )

    assert result.coverage.status == "partial"


def test_untracked_terraform_downloads_are_not_evidence(tmp_path) -> None:
    downloaded = 'resource "aws_cloudwatch_log_group" "this" {\n}\n'
    tracked = "infrastructure/staging/eks.tf"

    _collect(
        tmp_path,
        {
            tracked: EKS % "  enabled_log_types = []",
            "infrastructure/staging/.terraform/modules/eks/main.tf": downloaded,
        },
    )

    result = collector.collect(tmp_path, LIMITS, tracked_paths=frozenset({tracked}))

    assert result.coverage.status == "ok"
    assert result.evidence == ()
