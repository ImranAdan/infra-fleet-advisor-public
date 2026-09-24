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


def test_eks_version_must_pin_the_trusted_major(tmp_path) -> None:
    for version, trusted in {
        "21.25.0": True,
        "~> 21.0": True,
        "22.0.0": False,
        "20.37.0": False,
        ">= 18.0": False,
        "> 21.0": False,
        "~> 21": False,
        ">= 21.0, < 22.0": False,
    }.items():
        text = (EKS % "").replace("21.25.0", version)

        result = _collect(tmp_path, {"infrastructure/staging/eks.tf": text})

        assert (result.coverage.status == "ok") is trusted, version
        assert bool(_facts(result, EVIDENCE_KIND_LOG_RETENTION)) is trusted, version


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
    assert _facts(result, EVIDENCE_KIND_LOG_RETENTION) == []


PROVIDER = 'provider "aws" {\n  region = "eu-west-2"\n%s\n}\n'
COMPLETE_DEFAULTS = (
    '  default_tags {\n    tags = {\n      Environment = "staging"\n'
    '      Service     = "fleet"\n      Owner       = "platform"\n    }\n  }'
)
PARTIAL_TAGS = 'resource "aws_s3_bucket" "logs" {\n  tags = { Environment = "staging" }\n}\n'


def _tag_fact(tmp_path: Path, files: dict[str, str]) -> dict[str, object]:
    result = _collect(tmp_path, files)
    assert result.coverage.status == "ok"
    [fact] = _facts(result, collector.EVIDENCE_KIND_COST_TAGS)
    return fact


def test_resource_lacking_keys_the_defaults_lack_is_proven_untagged(tmp_path) -> None:
    fact = _tag_fact(
        tmp_path,
        {"infrastructure/staging/main.tf": PROVIDER % "" + PARTIAL_TAGS},
    )

    assert fact["cost_tags_incomplete"] is True
    assert fact["untagged_resources"] == "aws_s3_bucket.logs"
    assert fact["missing_default_tags"] == "environment, owner, service"


def test_complete_defaults_cover_partially_tagged_resources(tmp_path) -> None:
    fact = _tag_fact(
        tmp_path,
        {"infrastructure/staging/main.tf": PROVIDER % COMPLETE_DEFAULTS + PARTIAL_TAGS},
    )

    assert fact["default_tags_complete"] is True
    assert fact["cost_tags_incomplete"] is False


def test_missing_defaults_alone_are_not_a_divergence(tmp_path) -> None:
    self_tagged = (
        'resource "aws_s3_bucket" "logs" {\n  tags = {\n    Environment = "staging"\n'
        '    Service = "fleet"\n    Owner = "platform"\n  }\n}\n'
        'resource "aws_s3_bucket" "computed" {\n  tags = merge(local.a, local.b)\n}\n'
    )
    fact = _tag_fact(tmp_path, {"infrastructure/staging/main.tf": PROVIDER % "" + self_tagged})

    assert fact["default_tags_complete"] is False
    assert fact["cost_tags_incomplete"] is False


def test_default_tags_resolve_one_local_reference(tmp_path) -> None:
    locals_tf = (
        'locals {\n  region = "eu-west-2"\n  cost_tags = {\n'
        '    Environment = local.environment\n    Service = "fleet"\n'
        '    Owner = "platform"\n  }\n}\n'
    )
    fact = _tag_fact(
        tmp_path,
        {
            "infrastructure/staging/locals.tf": locals_tf,
            "infrastructure/staging/main.tf": PROVIDER
            % "  default_tags {\n    tags = local.cost_tags\n  }",
        },
    )

    assert fact["default_tags_complete"] is True


def test_computed_default_tags_are_partial_not_assumed(tmp_path) -> None:
    for tags in (
        "merge(local.a, local.b)",
        '{ Environment = "s", Service = "f", Owner = "p" } == {} ? {} : {}',
    ):
        result = _collect(
            tmp_path,
            {
                "infrastructure/staging/main.tf": PROVIDER
                % f"  default_tags {{\n    tags = {tags}\n  }}"
            },
        )

        assert result.coverage.status == "partial", tags
        assert _facts(result, collector.EVIDENCE_KIND_COST_TAGS) == []


NODE_GROUPS = """
  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.large"] # comment
      min_size       = 1
      max_size       = 2
      metadata_options = {
        http_tokens = "required"
      }
    }
  }"""


def _scaling(tmp_path: Path, files: dict[str, str]) -> list[dict[str, object]]:
    result = _collect(tmp_path, files)
    assert result.coverage.status == "ok"
    return _facts(result, collector.EVIDENCE_KIND_WORKER_SCALING)


def test_node_group_without_an_autoscaler_is_not_demand_scaled(tmp_path) -> None:
    [fact] = _scaling(tmp_path, {"infrastructure/staging/eks.tf": EKS % NODE_GROUPS})

    assert fact == {
        "min_size": 1,
        "max_size": 2,
        "explicit_max": True,
        "autoscaler_declared": False,
        "demand_scaled": False,
    }


def test_declared_autoscaler_drives_bounded_node_groups(tmp_path) -> None:
    for extra in (
        {
            "k8s/infrastructure/autoscaler.yaml": (
                "kind: HelmRelease\nspec:\n  chart:\n    spec:\n      chart: cluster-autoscaler\n"
            )
        },
        {
            "infrastructure/staging/karpenter.tf": (
                'resource "helm_release" "k" {\n  chart = "karpenter"\n}\n'
            )
        },
    ):
        [fact] = _scaling(tmp_path, {"infrastructure/staging/eks.tf": EKS % NODE_GROUPS, **extra})
        assert fact["demand_scaled"] is True, extra
        for path in extra:
            (tmp_path / path).unlink()


def test_autoscaler_mentioned_only_in_comments_does_not_count(tmp_path) -> None:
    [fact] = _scaling(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": EKS % NODE_GROUPS + "# TODO: add karpenter\n",
            "k8s/notes.yaml": "# cluster-autoscaler goes here\nkind: ConfigMap\n",
        },
    )

    assert fact["autoscaler_declared"] is False


def test_inactive_autoscaler_mentions_do_not_count(tmp_path) -> None:
    disabled = (
        'resource "helm_release" "k" {\n  count = 0\n  chart = "karpenter"\n}\n'
        'module "karpenter" {\n  count = 0\n  source = "example/karpenter/aws"\n}\n'
    )
    described = 'variable "x" {\n  description = "enable cluster-autoscaler later"\n}\n'
    [fact] = _scaling(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
            "infrastructure/staging/autoscaler.tf": disabled + described,
            "k8s/labels.yaml": "kind: ConfigMap\ndata:\n  owner: karpenter-team\n",
        },
    )

    assert fact["autoscaler_declared"] is False


def test_dynamic_autoscaler_enablement_makes_scaling_unverified(tmp_path) -> None:
    dynamic = (
        'module "karpenter" {\n  count = var.enable_karpenter ? 1 : 0\n'
        '  source = "example/karpenter/aws"\n}\n'
    )

    result = _collect(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
            "infrastructure/staging/autoscaler.tf": dynamic,
        },
    )

    assert result.coverage.status == "partial"
    assert "could not be evaluated" in (result.coverage.error_summary or "")
    assert _facts(result, collector.EVIDENCE_KIND_WORKER_SCALING) == []


def test_dynamic_enablement_on_unrelated_module_does_not_hide_scaling(tmp_path) -> None:
    [fact] = _scaling(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
            "infrastructure/staging/database.tf": (
                'module "database" {\n  count = var.enable_database ? 1 : 0\n'
                '  source = "example/database/aws"\n}\n'
            ),
        },
    )

    assert fact["autoscaler_declared"] is False


def test_incomplete_autoscaler_scan_withholds_scaling_evidence(tmp_path) -> None:
    files = {"infrastructure/staging/eks.tf": EKS % NODE_GROUPS, "k8s/bad.yaml": "a: [\n"}
    result = _collect(tmp_path, files)

    assert result.coverage.status == "partial"
    assert _facts(result, collector.EVIDENCE_KIND_WORKER_SCALING) == []


def test_public_eks_endpoint_is_accepted_only_in_staging(tmp_path) -> None:
    module = EKS % "  endpoint_public_access = true\n  enabled_log_types = []"
    cluster = (
        'resource "aws_eks_cluster" "prod" {\n  name = "p"\n'
        "  vpc_config {\n    subnet_ids = []\n  }\n}\n"
    )
    result = _collect(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": module,
            "infrastructure/production/eks.tf": cluster,
        },
    )

    facts = {
        f["staging_stack"]: f["exposure_accepted"]
        for f in _facts(result, collector.EVIDENCE_KIND_EKS_ENDPOINT)
    }
    # aws_eks_cluster defaults to a public endpoint, so production diverges.
    assert facts == {True: True, False: False}


def test_staging_capacity_needs_a_scheduled_release(tmp_path) -> None:
    eks = EKS % "  enabled_log_types = []"
    local_ci = (
        "on:\n  schedule: [{cron: '0 5 * * 1'}]\njobs:\n  a:\n    runs-on: x\n"
        "    steps:\n      - run: ./fleet down --profile local\n"
    )
    [fact] = _facts(
        _collect(
            tmp_path,
            {"infrastructure/staging/eks.tf": eks, ".github/workflows/local.yml": local_ci},
        ),
        collector.EVIDENCE_KIND_IDLE_CAPACITY,
    )
    assert fact["scheduled_release"] is False

    staging = local_ci.replace("--profile local", "--profile aws-staging")
    [fact] = _facts(
        _collect(tmp_path, {".github/workflows/local.yml": staging}),
        collector.EVIDENCE_KIND_IDLE_CAPACITY,
    )
    assert fact["scheduled_release"] is True

    (tmp_path / ".github" / "workflows" / "local.yml").unlink()
    minimum_only = 'resource "aws_autoscaling_schedule" "night" {\n  min_size = 0\n}\n'
    [fact] = _facts(
        _collect(tmp_path, {"infrastructure/staging/schedule.tf": minimum_only}),
        collector.EVIDENCE_KIND_IDLE_CAPACITY,
    )
    assert fact["scheduled_release"] is False
    schedule = (
        'resource "aws_autoscaling_schedule" "night" {\n  min_size = 0\n  desired_capacity = 0\n}\n'
    )
    [fact] = _facts(
        _collect(tmp_path, {"infrastructure/staging/schedule.tf": schedule}),
        collector.EVIDENCE_KIND_IDLE_CAPACITY,
    )
    assert fact["scheduled_release"] is True


def test_reusable_module_cluster_definitions_are_withheld(tmp_path) -> None:
    cluster = 'resource "aws_eks_cluster" "c" {\n  vpc_config {\n    subnet_ids = []\n  }\n}\n'
    result = _collect(tmp_path, {"infrastructure/modules/eks/main.tf": cluster})

    assert _facts(result, collector.EVIDENCE_KIND_EKS_ENDPOINT) == []


KARPENTER = 'module "%s" {\n  source = "terraform-aws-modules/eks/aws//modules/karpenter"\n%s\n}\n'


def test_multiline_literal_for_each_decides_autoscaler_enablement(tmp_path) -> None:
    for for_each, active in (
        ('  for_each = {\n    main = "a"\n  }', True),
        ("  for_each = {\n  }", False),
        ('  for_each = [\n    "a",\n  ]', True),
    ):
        [fact] = _scaling(
            tmp_path,
            {
                "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
                "infrastructure/staging/karpenter.tf": KARPENTER % ("k", for_each),
            },
        )
        assert fact["autoscaler_declared"] is active, for_each


def test_a_definite_autoscaler_settles_the_scan_in_any_order(tmp_path) -> None:
    dynamic = KARPENTER % ("maybe", "  count = var.enabled ? 1 : 0")
    definite = KARPENTER % ("always", "")
    for text in (dynamic + definite, definite + dynamic):
        [fact] = _scaling(
            tmp_path,
            {
                "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
                "infrastructure/staging/karpenter.tf": text,
            },
        )
        assert fact["autoscaler_declared"] is True


def test_uncertainty_in_one_file_does_not_outweigh_a_definite_one_elsewhere(tmp_path) -> None:
    [fact] = _scaling(
        tmp_path,
        {
            "infrastructure/staging/eks.tf": EKS % NODE_GROUPS,
            "infrastructure/staging/a_maybe.tf": KARPENTER % ("maybe", "  count = var.x"),
            "infrastructure/staging/b_always.tf": KARPENTER % ("always", ""),
        },
    )

    assert fact["autoscaler_declared"] is True
