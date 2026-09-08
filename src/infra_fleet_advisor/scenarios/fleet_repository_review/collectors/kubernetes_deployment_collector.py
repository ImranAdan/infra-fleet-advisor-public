import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
    K8S_DEPLOYMENT_COLLECTOR_ID,
    K8S_DEPLOYMENT_COLLECTOR_VERSION,
)

_DEFAULT_FENCEPOST = "25%"
_PERCENT = re.compile(r"^(0|[1-9][0-9]*)%$")
_MAX_DEPLOYMENT_EVIDENCE = 500


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _is_excluded(rel_path: str, excluded_paths: frozenset[str]) -> bool:
    return any(
        rel_path == excluded or rel_path.startswith(f"{excluded}/") for excluded in excluded_paths
    )


def _fencepost(value: Any, replicas: int, *, round_up: bool) -> tuple[str, int] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return str(value), value
    if not isinstance(value, str):
        return None
    match = _PERCENT.fullmatch(value)
    if match is None:
        return None
    percentage = int(match.group(1))
    scaled = replicas * percentage / 100
    effective = math.ceil(scaled) if round_up else math.floor(scaled)
    return value, effective


def _list_items(document: Mapping[Any, Any]) -> tuple[tuple[Mapping[Any, Any], ...], bool]:
    if document.get("kind") != "List":
        return (document,), False
    items = document.get("items")
    if not isinstance(items, list):
        return (), True
    if any(not isinstance(item, Mapping) for item in items):
        return (), True
    return tuple(items), False


def _build_deployment_evidence(
    resource: Mapping[Any, Any], rel_path: str
) -> tuple[Evidence | None, bool]:
    if resource.get("kind") != "Deployment":
        return None, False
    if resource.get("apiVersion") != "apps/v1":
        return None, True

    metadata = resource.get("metadata")
    spec = resource.get("spec")
    if not isinstance(metadata, Mapping) or not isinstance(spec, Mapping):
        return None, True
    name = metadata.get("name")
    namespace = metadata.get("namespace", "default")
    if not isinstance(name, str) or not name or not isinstance(namespace, str) or not namespace:
        return None, True

    replicas_value = spec.get("replicas", 1)
    if isinstance(replicas_value, bool) or not isinstance(replicas_value, int):
        return None, True
    if replicas_value < 0:
        return None, True

    strategy = spec.get("strategy", {})
    if not isinstance(strategy, Mapping):
        return None, True
    strategy_type = strategy.get("type", "RollingUpdate")
    if not isinstance(strategy_type, str):
        return None, True

    max_unavailable_text = "n/a"
    max_surge_text = "n/a"
    effective_max_unavailable = replicas_value
    effective_max_surge = 0
    if strategy_type == "RollingUpdate":
        rolling_update = strategy.get("rollingUpdate", {})
        if not isinstance(rolling_update, Mapping):
            return None, True
        max_unavailable = _fencepost(
            rolling_update.get("maxUnavailable", _DEFAULT_FENCEPOST),
            replicas_value,
            round_up=False,
        )
        max_surge = _fencepost(
            rolling_update.get("maxSurge", _DEFAULT_FENCEPOST),
            replicas_value,
            round_up=True,
        )
        if max_unavailable is None or max_surge is None:
            return None, True
        max_unavailable_text, effective_max_unavailable = max_unavailable
        max_surge_text, effective_max_surge = max_surge
    elif strategy_type != "Recreate":
        return None, True

    template = spec.get("template")
    pod_spec = template.get("spec") if isinstance(template, Mapping) else None
    containers = pod_spec.get("containers") if isinstance(pod_spec, Mapping) else None
    if (
        not isinstance(containers, list)
        or not containers
        or any(not isinstance(container, Mapping) for container in containers)
    ):
        return None, True
    all_containers_have_readiness_probe = all(
        isinstance(container.get("readinessProbe"), Mapping) for container in containers
    )

    has_active_replicas = replicas_value > 0
    retains_healthy_capacity = not has_active_replicas or (
        strategy_type == "RollingUpdate"
        and effective_max_unavailable == 0
        and effective_max_surge > 0
        and all_containers_have_readiness_probe
    )
    resource_name = f"{namespace}/{name}"
    return (
        build_evidence(
            collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
            collector_version=K8S_DEPLOYMENT_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
            source_path=rel_path,
            locator=f"Deployment/{resource_name}",
            excerpt=(
                f"Deployment {resource_name}: replicas={replicas_value}, "
                f"strategy={strategy_type}, maxUnavailable={max_unavailable_text}, "
                f"maxSurge={max_surge_text}"
            ),
            fact={
                "replicas": replicas_value,
                "strategy_type": strategy_type,
                "max_unavailable": max_unavailable_text,
                "max_surge": max_surge_text,
                "effective_max_unavailable": effective_max_unavailable,
                "effective_max_surge": effective_max_surge,
                "all_containers_have_readiness_probe": all_containers_have_readiness_probe,
                "retains_healthy_capacity": retains_healthy_capacity,
            },
            # A namespaced Kubernetes object is a stable resource handle. File
            # moves should not turn one unchanged desired object into a new issue.
            identity_parts=("apps/v1", "Deployment", namespace, name),
        ),
        False,
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    checkout_real = checkout_root.resolve()
    manifests_dir = checkout_root / "k8s"
    if not manifests_dir.exists():
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(K8S_DEPLOYMENT_COLLECTOR_ID, "ok", 0),
        )
    if not manifests_dir.is_dir() or not manifests_dir.resolve().is_relative_to(checkout_real):
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                K8S_DEPLOYMENT_COLLECTOR_ID,
                "failed",
                0,
                "k8s directory escapes the verified checkout",
            ),
        )

    all_files = sorted(
        path
        for path in manifests_dir.rglob("*")
        if path.suffix.lower() in {".yml", ".yaml"} and path.is_file()
    )
    files = all_files[: limits.max_manifest_files]
    omitted_files = len(all_files) - len(files)
    failures = 0
    excluded_count = 0
    untracked_count = 0
    deployment_limit_reached = False
    evidence_by_id: dict[str, Evidence] = {}
    duplicate_ids: set[str] = set()

    for path in files:
        rel_path = path.relative_to(checkout_root).as_posix()
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
            continue
        if tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
            continue
        try:
            if not path.resolve().is_relative_to(checkout_real):
                failures += 1
                continue
            if path.stat().st_size > limits.max_manifest_file_bytes:
                failures += 1
                continue
            documents = tuple(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError):
            failures += 1
            continue

        for document in documents:
            if document is None:
                continue
            if not isinstance(document, Mapping):
                failures += 1
                continue
            resources, list_failed = _list_items(document)
            failures += int(list_failed)
            for resource in resources:
                item, item_failed = _build_deployment_evidence(resource, rel_path)
                failures += int(item_failed)
                if item is None:
                    continue
                if len(evidence_by_id) >= _MAX_DEPLOYMENT_EVIDENCE:
                    deployment_limit_reached = True
                    continue
                if item.evidence_id in evidence_by_id:
                    duplicate_ids.add(item.evidence_id)
                    continue
                evidence_by_id[item.evidence_id] = item

    for duplicate_id in duplicate_ids:
        evidence_by_id.pop(duplicate_id, None)
    failures += len(duplicate_ids)

    reasons: list[str] = []
    if failures:
        reasons.append(f"{failures} manifest or resource(s) could not be evaluated")
    if omitted_files:
        reasons.append(f"{omitted_files} manifest file(s) omitted by safety limit")
    if excluded_count:
        reasons.append(f"{excluded_count} manifest file(s) excluded by policy")
    if untracked_count:
        reasons.append(f"{untracked_count} manifest file(s) not part of the verified commit")
    if deployment_limit_reached:
        reasons.append("deployment evidence omitted by safety limit")
    status = "partial" if reasons else "ok"
    evidence = tuple(evidence_by_id[key] for key in sorted(evidence_by_id))
    return CollectorResult(
        evidence=evidence,
        coverage=CollectorCoverage(
            collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
            status=status,
            evidence_count=len(evidence),
            error_summary="; ".join(reasons) or None,
        ),
    )
