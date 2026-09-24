import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.paths import validate_repo_relative_path
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.terraform_iam_collector import (  # noqa: E501
    _extract_balanced,
    _extract_policy_json,
    _iter_resource_blocks,
    _LiteralParser,
    _mask_non_code,
    _Traversal,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_COST_TAGS,
    EVIDENCE_KIND_ECR_LIFECYCLE,
    EVIDENCE_KIND_EKS_ENDPOINT,
    EVIDENCE_KIND_IDLE_CAPACITY,
    EVIDENCE_KIND_LOG_RETENTION,
    EVIDENCE_KIND_WORKER_SCALING,
    TF_COST_COLLECTOR_ID,
    TF_COST_COLLECTOR_VERSION,
)

_RESOURCE_HEADER = re.compile(
    r'resource\s+"(aws_cloudwatch_log_group|aws_ecr_repository|aws_ecr_lifecycle_policy'
    r'|aws_eks_cluster|aws_autoscaling_schedule)"'
    r'\s+"([A-Za-z0-9_-]+)"\s*\{'
)
_MODULE_HEADER = re.compile(r'(module)\s+"([A-Za-z0-9_-]+)"\s*\{')
_TAGGABLE_HEADER = re.compile(r'resource\s+"(aws_[A-Za-z0-9_]+)"\s+"([A-Za-z0-9_-]+)"\s*\{')
_PROVIDER_HEADER = re.compile(r'(provider)\s+"(aws)"\s*\{')
_LOCALS_HEADER = re.compile(r"(locals)\s*()\{")
_DEFAULT_TAGS_HEADER = re.compile(r"(default_tags)\s*()\{")
_LOCAL_REFERENCE = re.compile(r"^local\.([A-Za-z_][A-Za-z0-9_]*)$")
_COST_TAG_KEYS = frozenset({"environment", "service", "owner"})
_ECR_REFERENCE = re.compile(r"^aws_ecr_repository\.([A-Za-z0-9_-]+)\.(?:name|id)$")
_MAX_RETENTION_DAYS = 30

# The advisor never downloads modules, so a registry module's log group is
# derived from its published defaults. Only v21 defaults and variable names were
# checked; an exact v21 version or a ~> 21.x constraint must pin that major, and
# anything else is an explicit coverage gap.
_EKS_MODULE_SOURCE = "terraform-aws-modules/eks/aws"
_EKS_MODULE_VERSION = re.compile(r"^(?:=\s*)?21\.[0-9]+\.[0-9]+$|^~>\s*21\.[0-9]+(?:\.[0-9]+)?$")
_EKS_DEFAULT_RETENTION_DAYS = 90
# A managed node group only scales on demand when something drives it: a
# cluster-autoscaler or Karpenter installation, or EKS Auto Mode.
_NODE_AUTOSCALER = re.compile(r"\b(?:cluster-autoscaler|karpenter)\b")
_VPC_CONFIG_HEADER = re.compile(r"(vpc_config)\s*()\{")
_STAGING = "infrastructure/staging"
# A scheduled teardown of AWS staging: a run step that destroys Terraform state
# or brings the aws-staging profile down. The local profile's CI teardown of a
# throwaway kind cluster releases no AWS capacity and does not count.
_TEARDOWN_COMMAND = re.compile(
    r"terraform\b[^\n]*\bdestroy\b|\./fleet\s+down\b[^\n]*--profile[ =]aws-staging\b"
)
_HELM_RELEASE_HEADER = re.compile(r'resource\s+"(helm_release)"\s+"([A-Za-z0-9_-]+)"\s*\{')


def _declares_autoscaler_in_yaml(text: str) -> bool:
    """An active Kubernetes declaration: a Flux HelmRelease of the chart, or a
    Deployment running its image. Mentions in names, labels or docs do not count."""
    for document in yaml.safe_load_all(text):
        if not isinstance(document, dict):
            continue
        raw_spec = document.get("spec")
        spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}
        if document.get("kind") == "HelmRelease":
            chart = spec.get("chart", {})
            chart_spec = chart.get("spec", {}) if isinstance(chart, dict) else {}
            name = chart_spec.get("chart") if isinstance(chart_spec, dict) else None
            if isinstance(name, str) and _NODE_AUTOSCALER.search(name):
                return True
        if document.get("kind") == "Deployment":
            template = spec.get("template", {})
            pod = template.get("spec", {}) if isinstance(template, dict) else {}
            containers = pod.get("containers", []) if isinstance(pod, dict) else []
            if any(
                isinstance(c, dict)
                and isinstance(c.get("image"), str)
                and _NODE_AUTOSCALER.search(c["image"])
                for c in containers
                if isinstance(containers, list)
            ):
                return True
    return False


def _declares_autoscaler_in_terraform(text: str) -> bool:
    """An enabled helm_release of the chart, or a Karpenter module."""
    releases, _ = _iter_resource_blocks(text, _HELM_RELEASE_HEADER)
    for _kind, _name, body in releases:
        try:
            chart, count = _attribute(body, "chart"), _attribute(body, "count", 1)
        except ValueError:
            continue
        if isinstance(chart, str) and _NODE_AUTOSCALER.search(chart) and count != 0:
            return True
    modules, _ = _iter_resource_blocks(text, _MODULE_HEADER)
    for _kind, _name, body in modules:
        try:
            source = _attribute(body, "source")
        except ValueError:
            continue
        if isinstance(source, str) and "karpenter" in source:
            return True
    return False


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _attribute(body: str, name: str, default: Any = None) -> Any:
    """Return a single-line top-level literal attribute, or `default` when absent.

    Raises ValueError for duplicates and for values that are not bounded
    literals, such as variables or multi-line expressions."""
    code = _mask_non_code(body)
    pattern = re.compile(rf"(?<![\w.]){re.escape(name)}\s*=")
    hits = [
        match
        for match in pattern.finditer(code)
        if code[: match.start()].count("{") - code[: match.start()].count("}") == 1
    ]
    if not hits:
        return default
    if len(hits) > 1:
        raise ValueError(f"duplicate {name}")
    line_end = body.find("\n", hits[0].end())
    parser = _LiteralParser(
        _mask_non_code(body[hits[0].end() : line_end if line_end >= 0 else None], strings=False)
    )
    value = parser.value()
    if parser.index != len(parser.tokens):
        raise ValueError(f"{name} is not a single literal")
    return value


def _object_attribute(body: str, name: str) -> Any:
    """Like `_attribute`, but also reads a multi-line `{ ... }` object literal."""
    code = _mask_non_code(body)
    pattern = re.compile(rf"(?<![\w.]){re.escape(name)}\s*=\s*")
    hits = [
        match
        for match in pattern.finditer(code)
        if code[: match.start()].count("{") - code[: match.start()].count("}") == 1
    ]
    if len(hits) != 1 or code[hits[0].end() : hits[0].end() + 1] != "{":
        return _attribute(body, name)
    literal, after = _extract_balanced(body, hits[0].end(), "{", "}")
    line_end = body.find("\n", after)
    if _mask_non_code(body[after : line_end if line_end >= 0 else None]).strip(" \t\r}"):
        # The object is only part of a computed expression, e.g. a conditional.
        raise ValueError(f"{name} is not a single literal")
    parser = _LiteralParser(_mask_non_code(literal, strings=False))
    value = parser.value()
    if parser.index != len(parser.tokens):
        raise ValueError(f"{name} is not a single literal")
    return value


def _resolve_tags(value: Any, locals_bodies: list[str]) -> dict[str, Any]:
    """A literal tag map, or one level of `local.name`, the usual home for shared tags."""
    if isinstance(value, _Traversal):
        reference = _LOCAL_REFERENCE.fullmatch(value.value)
        if reference is None:
            raise ValueError("tags reference a non-local value")
        found = [
            resolved
            for body in locals_bodies
            if (resolved := _object_attribute(body, reference.group(1))) is not None
        ]
        if len(found) != 1:
            raise ValueError("tags reference an unresolved value")
        value = found[0]
    if not isinstance(value, dict):
        raise ValueError("tags are not a literal object")
    return value


def _tag_evidence(
    rel_path: str,
    provider_body: str,
    locals_bodies: list[str],
    tagged_blocks: list[tuple[str, str]],
) -> Evidence:
    """Which cost-allocation keys one AWS provider applies by default, and which
    resources in its root module provably carry none of the missing keys.

    Absent default_tags alone proves nothing: a resource may tag itself. A block
    counts as untagged only when its own readable `tags` lack a key the defaults
    also lack; unreadable tag expressions are skipped rather than assumed."""
    alias = _attribute(provider_body, "alias")
    locator = "provider.aws" + (f".{alias}" if isinstance(alias, str) else "")
    blocks, unbalanced = _iter_resource_blocks(provider_body, _DEFAULT_TAGS_HEADER)
    if unbalanced or len(blocks) > 1:
        raise ValueError("default_tags is malformed")
    defaults = (
        _resolve_tags(_object_attribute(blocks[0][2], "tags"), locals_bodies) if blocks else {}
    )
    missing = _COST_TAG_KEYS - {str(key).lower() for key in defaults}
    untagged = []
    if missing and not isinstance(alias, str):
        for address, body in tagged_blocks:
            try:
                if _attribute(body, "provider") is not None:
                    continue
                tags = _resolve_tags(_object_attribute(body, "tags"), locals_bodies)
            except ValueError:
                continue
            if missing - {str(key).lower() for key in tags}:
                untagged.append(address)
    root_module = PurePosixPath(rel_path).parent.as_posix()
    return build_evidence(
        collector_id=TF_COST_COLLECTOR_ID,
        collector_version=TF_COST_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_COST_TAGS,
        source_path=rel_path,
        locator=locator,
        excerpt=(
            f"{locator} default_tags lack: {', '.join(sorted(missing)) or 'nothing'}"
            + (f"; untagged: {', '.join(untagged[:5])}" if untagged else "")
        ),
        fact={
            "default_tags_complete": not missing,
            "missing_default_tags": ", ".join(sorted(missing)),
            "untagged_resources": ", ".join(untagged[:5]),
            "cost_tags_incomplete": bool(untagged),
        },
        identity_parts=(root_module, locator),
    )


def _retention_evidence(rel_path: str, locator: str, retention_days: int, excerpt: str) -> Evidence:
    root_module = PurePosixPath(rel_path).parent.as_posix()
    return build_evidence(
        collector_id=TF_COST_COLLECTOR_ID,
        collector_version=TF_COST_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_LOG_RETENTION,
        source_path=rel_path,
        locator=locator,
        excerpt=excerpt,
        fact={
            # 0 means CloudWatch never expires the events.
            "retention_days": retention_days,
            "bounded_retention": 0 < retention_days <= _MAX_RETENTION_DAYS,
        },
        identity_parts=(root_module, locator),
    )


def _log_group_evidence(rel_path: str, name: str, body: str) -> Evidence:
    retention = _attribute(body, "retention_in_days", 0)
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 0:
        raise ValueError("retention_in_days is not a literal day count")
    shown = f"{retention} days" if retention else "never expires"
    return _retention_evidence(
        rel_path,
        f"resource.aws_cloudwatch_log_group.{name}",
        retention,
        f"aws_cloudwatch_log_group.{name}: retention {shown}",
    )


def _eks_module_evidence(rel_path: str, name: str, body: str) -> Evidence | None:
    version = _attribute(body, "version")
    if not isinstance(version, str) or not _EKS_MODULE_VERSION.fullmatch(version.strip()):
        raise ValueError("EKS module version has no trusted log-group defaults")
    log_types = _attribute(body, "enabled_log_types", ["audit", "api", "authenticator"])
    create = _attribute(body, "create_cloudwatch_log_group", True)
    retention = _attribute(
        body, "cloudwatch_log_group_retention_in_days", _EKS_DEFAULT_RETENTION_DAYS
    )
    if (
        not isinstance(log_types, list)
        or not isinstance(create, bool)
        or isinstance(retention, bool)
        or not isinstance(retention, int)
        or retention < 0
    ):
        raise ValueError("EKS module log settings are not literals")
    if not log_types:
        return None
    locator = f"module.{name}.aws_cloudwatch_log_group.this"
    if not create:
        # EKS then creates /aws/eks/<cluster>/cluster itself, with no expiry.
        return _retention_evidence(
            rel_path,
            locator,
            0,
            f"module.{name}: control-plane logging on, log group left to AWS (never expires)",
        )
    return _retention_evidence(
        rel_path,
        locator,
        retention,
        f"module.{name} ({_EKS_MODULE_SOURCE} {version}): control-plane log group "
        f"retention {retention} days",
    )


def _worker_scaling_evidence(
    rel_path: str, name: str, body: str, autoscaler_declared: bool
) -> list[Evidence]:
    """One record per EKS managed node group: bounds and whether demand can move them."""
    groups = _object_attribute(body, "eks_managed_node_groups")
    if groups is None:
        return []
    if not isinstance(groups, dict) or not all(isinstance(g, dict) for g in groups.values()):
        raise ValueError("eks_managed_node_groups is not a literal object")
    auto_mode = _object_attribute(body, "compute_config")
    driven = autoscaler_declared or (
        isinstance(auto_mode, dict) and auto_mode.get("enabled") is True
    )
    root_module = PurePosixPath(rel_path).parent.as_posix()
    evidence = []
    for group_name, group in sorted(groups.items()):
        bounds = [group.get("min_size", 1), group.get("max_size", 3)]
        if not all(isinstance(b, int) and not isinstance(b, bool) for b in bounds):
            raise ValueError("node group bounds are not literal integers")
        min_size, max_size = bounds
        locator = f"module.{name}.eks_managed_node_groups.{group_name}"
        evidence.append(
            build_evidence(
                collector_id=TF_COST_COLLECTOR_ID,
                collector_version=TF_COST_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_WORKER_SCALING,
                source_path=rel_path,
                locator=locator,
                excerpt=(
                    f"{locator}: min {min_size}, max {max_size}; node autoscaler "
                    f"{'declared' if driven else 'not declared'}"
                ),
                fact={
                    "min_size": min_size,
                    "max_size": max_size,
                    "explicit_max": "max_size" in group,
                    "autoscaler_declared": driven,
                    "demand_scaled": driven and "max_size" in group and max_size > min_size,
                },
                identity_parts=(root_module, locator),
            )
        )
    return evidence


def _endpoint_evidence(rel_path: str, locator: str, public: bool) -> Evidence | None:
    root_module = PurePosixPath(rel_path).parent.as_posix()
    if "modules" in PurePosixPath(root_module).parts:
        # A reusable module's environment is its caller's; withhold rather than
        # guess from where the definition lives.
        return None
    staging = root_module == _STAGING or root_module.startswith(f"{_STAGING}/")
    return build_evidence(
        collector_id=TF_COST_COLLECTOR_ID,
        collector_version=TF_COST_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_EKS_ENDPOINT,
        source_path=rel_path,
        locator=locator,
        excerpt=f"{locator}: public API endpoint {str(public).lower()} in {root_module}",
        fact={
            "public_endpoint": public,
            "staging_stack": staging,
            "exposure_accepted": not public or staging,
        },
        identity_parts=(root_module, locator),
    )


def _cluster_endpoint_public(body: str) -> bool:
    """aws_eks_cluster enables the public endpoint unless vpc_config says otherwise."""
    blocks, unbalanced = _iter_resource_blocks(body, _VPC_CONFIG_HEADER)
    if unbalanced or len(blocks) != 1:
        raise ValueError("aws_eks_cluster needs exactly one vpc_config block")
    public = _attribute(blocks[0][2], "endpoint_public_access", True)
    if not isinstance(public, bool):
        raise ValueError("endpoint_public_access is not a literal")
    return public


def _schedules_teardown(text: str) -> bool:
    """A tracked workflow that runs a teardown command on a schedule."""
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return False
    triggers = workflow.get("on", workflow.get(True))
    if not isinstance(triggers, dict) or not triggers.get("schedule"):
        return False
    jobs = workflow.get("jobs")
    return isinstance(jobs, dict) and any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and _TEARDOWN_COMMAND.search(step["run"]) is not None
        for job in jobs.values()
        if isinstance(job, dict)
        for step in job.get("steps") or []
    )


def _lifecycle_rules(policy: dict[str, Any]) -> tuple[bool, bool]:
    """Return (expires_untagged, bounds_retained_images) for an ECR lifecycle policy."""
    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("ECR lifecycle policy has no rules")
    expires_untagged = False
    bounds_all = False
    for rule in rules:
        action = rule.get("action") if isinstance(rule, dict) else None
        selection = rule.get("selection") if isinstance(rule, dict) else None
        if not isinstance(action, dict) or not isinstance(selection, dict):
            raise ValueError("ECR lifecycle rule is malformed")
        if action.get("type") != "expire":
            continue
        tag_status = selection.get("tagStatus")
        count = selection.get("countNumber")
        bounded = (
            selection.get("countType") in {"imageCountMoreThan", "sinceImagePushed"}
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
        )
        expires_untagged = expires_untagged or tag_status in {"untagged", "any"}
        covers_every_image = tag_status == "any" or (
            tag_status == "tagged" and selection.get("tagPatternList") == ["*"]
        )
        bounds_all = bounds_all or (bounded and covers_every_image)
    return expires_untagged, bounds_all


def _ecr_evidence(
    repositories: dict[tuple[str, str], tuple[str, str]],
    policies: list[tuple[str, str, str]],
) -> tuple[list[Evidence], int]:
    """Join repositories to lifecycle policies within each root module."""
    failures = 0
    by_repository: dict[tuple[str, str], list[tuple[bool, bool]]] = {}
    names_by_literal = {
        (module, literal): name
        for (module, name), (_path, literal) in repositories.items()
        if literal
    }
    for module, policy_name, body in policies:
        try:
            reference = _attribute(body, "repository")
            if isinstance(reference, _Traversal):
                match = _ECR_REFERENCE.fullmatch(reference.value)
                target = match.group(1) if match else None
            elif isinstance(reference, str):
                target = names_by_literal.get((module, reference))
            else:
                target = None
            policy, _failed = _extract_policy_json(body)
            if target is None or (module, target) not in repositories or policy is None:
                raise ValueError(f"unresolved ECR lifecycle policy {policy_name}")
            by_repository.setdefault((module, target), []).append(_lifecycle_rules(policy))
        except ValueError:
            failures += 1

    evidence: list[Evidence] = []
    for (module, name), (rel_path, _literal) in sorted(repositories.items()):
        attached = by_repository.get((module, name), [])
        if len(attached) > 1:
            failures += 1
            continue
        expires_untagged, bounds_all = attached[0] if attached else (False, False)
        locator = f"resource.aws_ecr_repository.{name}"
        evidence.append(
            build_evidence(
                collector_id=TF_COST_COLLECTOR_ID,
                collector_version=TF_COST_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_ECR_LIFECYCLE,
                source_path=rel_path,
                locator=locator,
                excerpt=(
                    f"aws_ecr_repository.{name}: lifecycle policy "
                    f"{'present' if attached else 'absent'}, expires untagged="
                    f"{expires_untagged}, bounds retained images={bounds_all}"
                ),
                fact={
                    "has_lifecycle_policy": bool(attached),
                    "expires_untagged": expires_untagged,
                    "bounds_retained_images": bounds_all,
                    "bounded_lifecycle": expires_untagged and bounds_all,
                },
                identity_parts=(module, locator),
            )
        )
    return evidence, failures


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    checkout_real = checkout_root.resolve()
    infra_dir = checkout_root / "infrastructure"
    if not infra_dir.is_dir():
        return CollectorResult((), CollectorCoverage(TF_COST_COLLECTOR_ID, "ok", 0))
    if not infra_dir.resolve().is_relative_to(checkout_real):
        return CollectorResult(
            (),
            CollectorCoverage(
                TF_COST_COLLECTOR_ID,
                "failed",
                0,
                "infrastructure directory escapes the verified checkout",
            ),
        )

    eligible: list[Path] = []
    excluded_count = 0
    untracked_count = 0
    for path in sorted(infra_dir.rglob("*.tf")):
        rel_path = path.relative_to(checkout_root).as_posix()
        if ".terraform" in path.relative_to(infra_dir).parts and (
            tracked_paths is None or rel_path not in tracked_paths
        ):
            continue
        if any(rel_path == ex or rel_path.startswith(f"{ex}/") for ex in excluded_paths):
            excluded_count += 1
        elif tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
        else:
            eligible.append(path)
    files = eligible[: limits.max_workflow_files]
    truncated_count = len(eligible) - len(files)
    # Tracked Kubernetes manifests are scanned only for a node autoscaler, on
    # their own budget so a large k8s tree cannot crowd out Terraform files.
    manifests = sorted(
        path
        for path in (checkout_root / "k8s").rglob("*")
        if path.suffix in {".yaml", ".yml"}
        and (tracked_paths is None or path.relative_to(checkout_root).as_posix() in tracked_paths)
        and not any(
            path.relative_to(checkout_root).as_posix().startswith(f"{ex}/")
            or path.relative_to(checkout_root).as_posix() == ex
            for ex in excluded_paths
        )
    )
    truncated_count += max(0, len(manifests) - limits.max_manifest_files)
    files += manifests[: limits.max_manifest_files]
    # Tracked workflows are scanned only for a scheduled teardown (C-001).
    workflows = sorted(
        path
        for path in (checkout_root / ".github" / "workflows").glob("*.y*ml")
        if (tracked_paths is None or path.relative_to(checkout_root).as_posix() in tracked_paths)
        and not any(
            path.relative_to(checkout_root).as_posix() == ex
            or path.relative_to(checkout_root).as_posix().startswith(f"{ex}/")
            for ex in excluded_paths
        )
    )
    truncated_count += max(0, len(workflows) - limits.max_workflow_files)
    files += workflows[: limits.max_workflow_files]

    evidence: list[Evidence] = []
    repositories: dict[tuple[str, str], tuple[str, str]] = {}
    policies: list[tuple[str, str, str]] = []
    providers: list[tuple[str, str, str]] = []
    locals_by_module: dict[str, list[str]] = {}
    tagged_by_module: dict[str, list[tuple[str, str]]] = {}
    eks_modules: list[tuple[str, str, str]] = []
    autoscaler_declared = False
    scheduled_release: list[str] = []
    failures = 0
    for path in files:
        rel_path = path.relative_to(checkout_root).as_posix()
        module = PurePosixPath(rel_path).parent.as_posix()
        try:
            validate_repo_relative_path(rel_path)
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                failures += 1
                continue
            size_limit = (
                limits.max_file_bytes if path.suffix == ".tf" else limits.max_manifest_file_bytes
            )
            if path.stat().st_size > size_limit:
                failures += 1
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, UnsafePathError):
            failures += 1
            continue

        if rel_path.startswith(".github/workflows/"):
            try:
                if _schedules_teardown(text):
                    scheduled_release.append(f"scheduled teardown in {rel_path}")
            except yaml.YAMLError:
                failures += 1
            continue
        if rel_path.endswith((".yaml", ".yml")):
            try:
                autoscaler_declared = autoscaler_declared or _declares_autoscaler_in_yaml(text)
            except yaml.YAMLError:
                failures += 1
            continue
        autoscaler_declared = autoscaler_declared or _declares_autoscaler_in_terraform(text)
        resources, unbalanced = _iter_resource_blocks(text, _RESOURCE_HEADER)
        modules, module_unbalanced = _iter_resource_blocks(text, _MODULE_HEADER)
        provider_blocks, provider_unbalanced = _iter_resource_blocks(text, _PROVIDER_HEADER)
        locals_blocks, locals_unbalanced = _iter_resource_blocks(text, _LOCALS_HEADER)
        failures += unbalanced + module_unbalanced + provider_unbalanced + locals_unbalanced
        providers.extend((rel_path, module, body) for _kw, _name, body in provider_blocks)
        locals_by_module.setdefault(module, []).extend(body for _kw, _n, body in locals_blocks)
        taggable, taggable_unbalanced = _iter_resource_blocks(text, _TAGGABLE_HEADER)
        failures += taggable_unbalanced
        tagged_by_module.setdefault(module, []).extend(
            (f"{kind}.{name}", body) for kind, name, body in taggable if "tags" in body
        )
        tagged_by_module[module].extend(
            (f"module.{name}", body) for _kw, name, body in modules if "tags" in body
        )
        for resource_type, name, body in resources:
            try:
                if resource_type == "aws_cloudwatch_log_group":
                    evidence.append(_log_group_evidence(rel_path, name, body))
                elif resource_type == "aws_eks_cluster":
                    exposure = _endpoint_evidence(
                        rel_path, f"resource.aws_eks_cluster.{name}", _cluster_endpoint_public(body)
                    )
                    if exposure is not None:
                        evidence.append(exposure)
                elif resource_type == "aws_autoscaling_schedule":
                    # Lowering only the minimum leaves desired capacity running.
                    to_zero = _attribute(body, "desired_capacity") == 0
                    if to_zero and module.startswith(_STAGING):
                        scheduled_release.append(f"aws_autoscaling_schedule.{name}")
                elif resource_type == "aws_ecr_repository":
                    literal = _attribute(body, "name")
                    repositories[(module, name)] = (
                        rel_path,
                        literal if isinstance(literal, str) else "",
                    )
                else:
                    policies.append((module, name, body))
            except ValueError:
                failures += 1
        for _keyword, name, body in modules:
            try:
                if _attribute(body, "source") != _EKS_MODULE_SOURCE:
                    continue
                eks_modules.append((rel_path, name, body))
                # Validates the pinned major before any v21 default is trusted.
                item = _eks_module_evidence(rel_path, name, body)
                public = _attribute(body, "endpoint_public_access", False)
                if not isinstance(public, bool):
                    raise ValueError("endpoint_public_access is not a literal")
                exposure = _endpoint_evidence(rel_path, f"module.{name}", public)
                if exposure is not None:
                    evidence.append(exposure)
            except ValueError:
                failures += 1
                continue
            if item is not None:
                evidence.append(item)

    for rel_path, module, body in providers:
        try:
            evidence.append(
                _tag_evidence(
                    rel_path,
                    body,
                    locals_by_module.get(module, []),
                    tagged_by_module.get(module, []),
                )
            )
        except ValueError:
            failures += 1

    # Node groups are judged after every file is read: an autoscaler declared
    # anywhere in the tracked scope drives them. An absence is evidence only
    # when that whole scope was read, so an incomplete scan withholds them.
    scan_complete = not failures and not truncated_count
    for rel_path, name, body in eks_modules if autoscaler_declared or scan_complete else ():
        try:
            evidence.extend(_worker_scaling_evidence(rel_path, name, body, autoscaler_declared))
        except ValueError:
            failures += 1

    # C-001: staging worker capacity needs a scheduled release. An absence is
    # evidence only when the whole scope was read.
    for rel_path, name, _body in eks_modules if scheduled_release or scan_complete else ():
        if not rel_path.startswith(f"{_STAGING}/"):
            continue
        locator = f"module.{name} idle capacity"
        evidence.append(
            build_evidence(
                collector_id=TF_COST_COLLECTOR_ID,
                collector_version=TF_COST_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_IDLE_CAPACITY,
                source_path=rel_path,
                locator=locator,
                excerpt=(
                    f"{locator}: "
                    + ("; ".join(scheduled_release[:3]) or "no scheduled scale-down or teardown")
                ),
                fact={"scheduled_release": bool(scheduled_release)},
                identity_parts=(_STAGING, locator),
            )
        )

    ecr_items, ecr_failures = _ecr_evidence(repositories, policies)
    evidence.extend(ecr_items)
    failures += ecr_failures

    reasons = []
    if failures:
        reasons.append(f"{failures} Terraform cost resource(s) or file(s) could not be evaluated")
    if truncated_count:
        reasons.append(f"{truncated_count} Terraform file(s) omitted past max_workflow_files")
    if excluded_count:
        reasons.append(f"{excluded_count} Terraform file(s) excluded by policy")
    if untracked_count:
        reasons.append(f"{untracked_count} Terraform file(s) not part of the verified commit")
    ordered = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    return CollectorResult(
        evidence=ordered,
        coverage=CollectorCoverage(
            collector_id=TF_COST_COLLECTOR_ID,
            status="partial" if failures or truncated_count or untracked_count else "ok",
            evidence_count=len(ordered),
            error_summary="; ".join(reasons) or None,
        ),
    )
