"""Rollout and container facts for the Deployments each profile applies.

The target fleet uses Flux Kustomizations and profile overlays, so raw base
manifests are insufficient evidence of deployed desired state. Profiles are
rendered in-process through the same closed, read-only subset used by the
Kubernetes security collector. Facts for one workload are then combined across
profiles under its stable Kubernetes identity.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CONTAINER_HARDENING,
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
    K8S_DEPLOYMENT_COLLECTOR_ID,
    K8S_DEPLOYMENT_COLLECTOR_VERSION,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_renderer import (
    KUSTOMIZATION_FILES,
    render_profiles,
)

_DEFAULT_FENCEPOST = "25%"
_PERCENT = re.compile(r"^(0|[1-9][0-9]*)%$")
_MAX_DEPLOYMENT_EVIDENCE = 500
_MAX_INT_OR_PERCENT = 2_147_483_647
_MAX_PROFILES = 8
_PROTECTIVE_FACT = {
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY: "retains_healthy_capacity",
    EVIDENCE_KIND_CONTAINER_HARDENING: "all_containers_hardened",
}


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
        if value < 0 or value > _MAX_INT_OR_PERCENT:
            return None
        return str(value), value
    if not isinstance(value, str):
        return None
    match = _PERCENT.fullmatch(value)
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) > 10:
        return None
    percentage = int(digits)
    if percentage > _MAX_INT_OR_PERCENT:
        return None
    product = replicas * percentage
    effective = (product + 99) // 100 if round_up else product // 100
    return value, effective


def _list_items(document: Mapping[Any, Any]) -> tuple[tuple[Mapping[Any, Any], ...], bool]:
    if document.get("kind") != "List":
        return (document,), False
    items = document.get("items")
    if not isinstance(items, list):
        return (), True
    resources = tuple(item for item in items if isinstance(item, Mapping))
    return resources, len(resources) != len(items)


def _build_deployment_evidence(
    resource: Mapping[Any, Any], rel_path: str, patch_path: str | None = None
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
    if replicas_value < 0 or replicas_value > _MAX_INT_OR_PERCENT:
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
                + (f"; rendered patch={patch_path}" if patch_path else "")
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


def _is_hardened(container: Mapping[Any, Any], pod_context: Mapping[Any, Any]) -> bool | None:
    """Non-root, no privilege escalation, all capabilities dropped; None if malformed."""
    context = container.get("securityContext", {})
    if not isinstance(context, Mapping):
        return None
    capabilities = context.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        return None
    run_as_non_root = context.get("runAsNonRoot", pod_context.get("runAsNonRoot"))
    run_as_user = context.get("runAsUser", pod_context.get("runAsUser"))
    uid = (
        run_as_user if isinstance(run_as_user, int) and not isinstance(run_as_user, bool) else None
    )
    # An explicit UID 0 contradicts runAsNonRoot; Kubernetes refuses to start it.
    non_root = uid != 0 and (run_as_non_root is True or (uid is not None and uid > 0))
    drop = capabilities.get("drop", [])
    return (
        non_root
        and context.get("allowPrivilegeEscalation") is False
        and context.get("privileged") is not True
        and isinstance(drop, list)
        and "ALL" in drop
        and not capabilities.get("add")
    )


def _build_hardening_evidence(
    resource: Mapping[Any, Any], rel_path: str, patch_path: str | None = None
) -> tuple[Evidence | None, bool]:
    """Assumes the rollout evidence for this Deployment already validated its shape."""
    metadata = resource["metadata"]
    name = metadata["name"]
    namespace = metadata.get("namespace", "default")
    pod_spec = resource["spec"]["template"]["spec"]
    pod_context = pod_spec.get("securityContext", {})
    init_containers = pod_spec.get("initContainers", [])
    if not isinstance(pod_context, Mapping) or not isinstance(init_containers, list):
        return None, True
    containers = [*pod_spec["containers"], *init_containers]
    weak: list[str] = []
    for container in containers:
        hardened = _is_hardened(container, pod_context) if isinstance(container, Mapping) else None
        if hardened is None:
            return None, True
        if not hardened:
            weak.append(str(container.get("name", "?")))
    resource_name = f"{namespace}/{name}"
    return (
        build_evidence(
            collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
            collector_version=K8S_DEPLOYMENT_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_CONTAINER_HARDENING,
            source_path=rel_path,
            locator=f"Deployment/{resource_name}/securityContext",
            excerpt=(
                f"Deployment {resource_name}: {len(containers) - len(weak)}/{len(containers)} "
                "containers non-root, no privilege escalation, all capabilities dropped"
                + (f"; not hardened: {', '.join(weak[:10])}" if weak else "")
                + (f"; rendered patch={patch_path}" if patch_path else "")
            ),
            fact={"containers": len(containers), "all_containers_hardened": not weak},
            identity_parts=("apps/v1", "Deployment", namespace, name, "securityContext"),
        ),
        False,
    )


def _evaluate_documents(
    documents: Iterable[tuple[Any, str, str | None]],
) -> tuple[tuple[Evidence, ...], int, bool]:
    failures = 0
    deployment_limit_reached = False
    evidence_by_id: dict[str, Evidence] = {}
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for document, rel_path, patch_path in documents:
        if document is None:
            continue
        if not isinstance(document, Mapping):
            failures += 1
            continue
        resources, list_failed = _list_items(document)
        failures += int(list_failed)
        for resource in resources:
            rollout, item_failed = _build_deployment_evidence(resource, rel_path, patch_path)
            failures += int(item_failed)
            if rollout is None:
                continue
            hardening, item_failed = _build_hardening_evidence(resource, rel_path, patch_path)
            failures += int(item_failed)
            for item in (rollout, hardening):
                if item is None:
                    continue
                if item.evidence_id in seen_ids:
                    duplicate_ids.add(item.evidence_id)
                    evidence_by_id.pop(item.evidence_id, None)
                    continue
                seen_ids.add(item.evidence_id)
                if len(evidence_by_id) >= _MAX_DEPLOYMENT_EVIDENCE:
                    deployment_limit_reached = True
                    continue
                evidence_by_id[item.evidence_id] = item

    failures += len(duplicate_ids)
    evidence = tuple(evidence_by_id[key] for key in sorted(evidence_by_id))
    return evidence, failures, deployment_limit_reached


def _collect_raw(
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
    excluded_count = 0
    untracked_count = 0
    eligible_files: list[Path] = []
    for path in all_files:
        rel_path = path.relative_to(checkout_root).as_posix()
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
        elif tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
        else:
            eligible_files.append(path)

    files = eligible_files[: limits.max_manifest_files]
    omitted_files = len(eligible_files) - len(files)
    failures = 0
    documents: list[tuple[Any, str, str | None]] = []

    for path in files:
        rel_path = path.relative_to(checkout_root).as_posix()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                failures += 1
                continue
            if path.stat().st_size > limits.max_manifest_file_bytes:
                failures += 1
                continue
            parsed = tuple(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError):
            failures += 1
            continue

        documents.extend((document, rel_path, None) for document in parsed)

    evidence, evaluation_failures, deployment_limit_reached = _evaluate_documents(documents)
    failures += evaluation_failures

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
    return CollectorResult(
        evidence=evidence,
        coverage=CollectorCoverage(
            collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
            status=status,
            evidence_count=len(evidence),
            error_summary="; ".join(reasons) or None,
        ),
    )


def _combine_profiles(per_profile: dict[str, tuple[Evidence, ...]]) -> tuple[Evidence, ...]:
    """Keep resource identities stable while requiring controls in every profile."""
    grouped: dict[str, list[tuple[str, Evidence]]] = {}
    for profile, evidence in per_profile.items():
        for item in evidence:
            grouped.setdefault(item.evidence_id, []).append((profile, item))

    combined: list[Evidence] = []
    for evidence_id in sorted(grouped):
        entries = grouped[evidence_id]
        first = entries[0][1]
        protective_fact = _PROTECTIVE_FACT[first.kind]
        fact: dict[str, bool | str | int] = {}
        for key, value in first.fact.items():
            values = [item.fact.get(key) for _profile, item in entries]
            if key == protective_fact:
                fact[key] = all(item is True for item in values)
            elif all(item == values[0] for item in values):
                fact[key] = value
            else:
                fact[key] = ", ".join(sorted({str(item) for item in values}))

        failing = sorted(
            profile for profile, item in entries if item.fact.get(protective_fact) is not True
        )
        profiles = sorted(profile for profile, _item in entries)
        fact["profiles"] = ", ".join(profiles)
        fact["failing_profiles"] = ", ".join(failing)
        shown = next((item for profile, item in entries if profile in failing), first)
        combined.append(
            Evidence(
                evidence_id=first.evidence_id,
                kind=first.kind,
                source_path=shown.source_path,
                locator=first.locator,
                excerpt=f"[{', '.join(failing or profiles)}] {shown.excerpt}"[:280],
                fact=fact,
                collector_id=first.collector_id,
                collector_version=first.collector_version,
            )
        )
    return tuple(combined)


def _mark_unrendered(result: CollectorResult, reasons: list[str]) -> CollectorResult:
    summary_parts = [*reasons, "no deployment profiles; manifests evaluated unrendered"]
    if result.coverage.error_summary:
        summary_parts.append(result.coverage.error_summary)
    return CollectorResult(
        result.evidence,
        CollectorCoverage(
            K8S_DEPLOYMENT_COLLECTOR_ID,
            "failed" if result.coverage.status == "failed" else "partial",
            len(result.evidence),
            "; ".join(summary_parts)[:500],
        ),
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    if not (checkout_root / "k8s").exists():
        return _collect_raw(checkout_root, limits, excluded_paths, tracked_paths)
    clusters = checkout_root / "k8s" / "clusters"
    directories = (
        sorted(path for path in clusters.iterdir() if path.is_dir()) if clusters.is_dir() else []
    )
    if not directories:
        raw = _collect_raw(checkout_root, limits, excluded_paths, tracked_paths)
        return _mark_unrendered(raw, [])

    reasons: list[str] = []
    profiles: list[str] = []
    for directory in directories:
        if any((directory / name).is_file() for name in KUSTOMIZATION_FILES):
            profiles.append(directory.name)
        else:
            reasons.append(f"{directory.name}: no kustomization file, profile not rendered")
    if len(profiles) > _MAX_PROFILES:
        reasons.append(f"{len(profiles) - _MAX_PROFILES} profile(s) omitted by safety limit")
        profiles = profiles[:_MAX_PROFILES]
    if not profiles:
        raw = _collect_raw(checkout_root, limits, excluded_paths, tracked_paths)
        return _mark_unrendered(raw, reasons)

    per_profile: dict[str, tuple[Evidence, ...]] = {}
    for render in render_profiles(checkout_root, profiles, limits, tracked_paths, excluded_paths):
        reasons.extend(f"{render.profile}: {gap}" for gap in render.gaps)
        documents = (
            (resource.body, resource.source_path, resource.patch_path)
            for resource in render.resources
        )
        evidence, failures, limit_reached = _evaluate_documents(documents)
        per_profile[render.profile] = evidence
        if failures:
            reasons.append(
                f"{render.profile}: {failures} manifest or resource(s) could not be evaluated"
            )
        if limit_reached:
            reasons.append(f"{render.profile}: deployment evidence omitted by safety limit")

    evidence = _combine_profiles(per_profile)
    if len(evidence) > _MAX_DEPLOYMENT_EVIDENCE:
        evidence = evidence[:_MAX_DEPLOYMENT_EVIDENCE]
        reasons.append("deployment evidence omitted by safety limit")
    return CollectorResult(
        evidence,
        CollectorCoverage(
            K8S_DEPLOYMENT_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(evidence),
            "; ".join(reasons)[:500] or None,
        ),
    )
