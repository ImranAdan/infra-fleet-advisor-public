"""Platform operability facts for what each deployment profile applies.

Every `k8s/clusters/<profile>` is rendered in-process by profile_renderer, as
for the security and deployment collectors. From the renders this collector
reads:

- HelmRelease recovery: a timeout and install/upgrade remediation retries (R-002);
- canary rollback for each delivered application Deployment (R-003);
- disruption survival on AWS staging: two or more replicas and a budget (R-005);
- Pod Security `restricted` enforcement on application namespaces (S-016);
- the local profile's declared resource requests against a budget (C-006);
- bounded Prometheus retention (C-007);
- that every platform manifest is reached by some profile (G-001).

Outside the renders it reads two literal sources: application catalog
directories, whose messaging apps must declare a channel prefix in their
contract (R-004), and app publish workflows, which must feed DORA (M-008).
HelmRelease chart output is never rendered: only values written in Git count.
"""

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
    EVIDENCE_KIND_CANARY_ROLLBACK,
    EVIDENCE_KIND_DECLARED_FOOTPRINT,
    EVIDENCE_KIND_DISRUPTION_BUDGET,
    EVIDENCE_KIND_DORA_COVERAGE,
    EVIDENCE_KIND_HELM_RECOVERY,
    EVIDENCE_KIND_MANIFEST_REACHABILITY,
    EVIDENCE_KIND_MESSAGING_CONTRACT,
    EVIDENCE_KIND_METRICS_RETENTION,
    EVIDENCE_KIND_POD_SECURITY,
    PLATFORM_COLLECTOR_ID,
    PLATFORM_COLLECTOR_VERSION,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_evidence import (
    combine_profiles,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_renderer import (
    KUSTOMIZATION_FILES,
    RenderedResource,
    render_profiles,
)

_APPLICATIONS = "k8s/applications/"
# The shared application template; every other directory under
# k8s/applications/ is an on-demand catalog entry the control plane launches.
_PLATFORM_TEMPLATE = "k8s/applications/platform/"
# Flux's bootstrap is applied by `flux bootstrap`, not by a profile.
_BOOTSTRAP = "k8s/flux-system/"
_LOCAL_PROFILE = "local"
_AWS_PROFILE = "aws-staging"
# C-006's declared budget for what the local profile requests in Git.
_LOCAL_CPU_BUDGET_MILLICORES = 1000
_LOCAL_MEMORY_BUDGET_MIB = 2048
_METRICS_CHART = "kube-prometheus-stack"
_DORA_WORKFLOW = ".github/workflows/dora-metrics.yml"
_PUBLISH_WORKFLOW = re.compile(r"^\.github/workflows/[a-z0-9][-a-z0-9]*-publish\.ya?ml$")
_CATALOG_ENTRY = re.compile(r"^k8s/applications/([a-z0-9][-a-z0-9]*)/")
_MESSAGING_PREFIX = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_PROFILES = 8
_MAX_SHOWN = 5
_POD_TEMPLATE_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
_PROTECTIVE = frozenset(
    {
        "recovers",
        "canary_rolls_back",
        "enforces_restricted",
        "retention_bounded",
    }
)


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _evidence(
    kind: str,
    source_path: str,
    locator: str,
    excerpt: str,
    fact: dict[str, Any],
    identity: tuple[str, ...],
) -> Evidence:
    return build_evidence(
        collector_id=PLATFORM_COLLECTOR_ID,
        collector_version=PLATFORM_COLLECTOR_VERSION,
        kind=kind,
        source_path=source_path,
        locator=locator,
        excerpt=excerpt[:280],
        fact=fact,
        identity_parts=(kind, *identity),
    )


def _meta(body: Mapping[str, Any]) -> tuple[str, str]:
    metadata = body.get("metadata") or {}
    return str(metadata.get("namespace") or "default"), str(metadata.get("name") or "")


def _spec(body: Mapping[str, Any]) -> Mapping[str, Any]:
    spec = body.get("spec")
    return spec if isinstance(spec, Mapping) else {}


def _retries(block: Any) -> int:
    remediation = block.get("remediation") if isinstance(block, Mapping) else None
    retries = remediation.get("retries") if isinstance(remediation, Mapping) else None
    return retries if isinstance(retries, int) and not isinstance(retries, bool) else 0


def _helm_recovery(resource: RenderedResource) -> Evidence:
    spec = _spec(resource.body)
    namespace, name = _meta(resource.body)
    timeout = isinstance(spec.get("timeout"), str) and bool(spec["timeout"])
    install, upgrade = _retries(spec.get("install")), _retries(spec.get("upgrade"))
    upgrade_block = spec.get("upgrade")
    remediation = upgrade_block.get("remediation") if isinstance(upgrade_block, Mapping) else None
    # Flux rolls back by default; `uninstall` deletes the release instead.
    rolls_back = isinstance(remediation, Mapping) and remediation.get("strategy") != "uninstall"
    recovers = timeout and install > 0 and upgrade > 0 and rolls_back
    return _evidence(
        EVIDENCE_KIND_HELM_RECOVERY,
        resource.source_path,
        f"HelmRelease/{namespace}/{name}",
        f"{name}: timeout {'set' if timeout else 'unset'}; install retries {install}; "
        f"upgrade retries {upgrade}; upgrade rolls back: {str(rolls_back).lower()}",
        {
            "timeout_set": timeout,
            "install_retries": install,
            "upgrade_retries": upgrade,
            "recovers": recovers,
        },
        ("HelmRelease", namespace, name),
    )


def _template(body: Mapping[str, Any]) -> Mapping[str, Any]:
    spec = _spec(body)
    if body.get("kind") == "CronJob":
        spec = _spec(spec.get("jobTemplate") or {})
    template = spec.get("template")
    return template if isinstance(template, Mapping) else {}


def _labels(body: Mapping[str, Any]) -> Mapping[str, Any]:
    labels = (_template(body).get("metadata") or {}).get("labels") or {}
    return labels if isinstance(labels, Mapping) else {}


def _app_deployments(resources: list[RenderedResource]) -> list[RenderedResource]:
    return [
        r
        for r in resources
        if r.body.get("kind") == "Deployment" and r.source_path.startswith(_APPLICATIONS)
    ]


def _canary(deployment: RenderedResource, resources: list[RenderedResource]) -> Evidence:
    namespace, name = _meta(deployment.body)
    canaries = []
    for resource in resources:
        if resource.body.get("kind") != "Canary" or _meta(resource.body)[0] != namespace:
            continue
        target = _spec(resource.body).get("targetRef") or {}
        if isinstance(target, Mapping) and target.get("name") == name:
            canaries.append(resource)
    ok = []
    for canary in canaries:
        analysis = _spec(canary.body).get("analysis") or {}
        if not isinstance(analysis, Mapping):
            continue
        threshold, weight = analysis.get("threshold"), analysis.get("maxWeight")
        metrics = analysis.get("metrics")
        if (
            isinstance(threshold, int)
            and threshold >= 1
            and isinstance(weight, int)
            and 0 < weight < 100
            and isinstance(metrics, list)
            and metrics
        ):
            ok.append(_meta(canary.body)[1])
    return _evidence(
        EVIDENCE_KIND_CANARY_ROLLBACK,
        deployment.source_path,
        f"Deployment/{namespace}/{name}/canary",
        f"{name}: {len(canaries)} Canary target(s) it; "
        f"{len(ok)} analyse metrics with a failure threshold below full weight",
        {"canaries": len(canaries), "canary_rolls_back": bool(ok)},
        ("Deployment", namespace, name),
    )


def _selects(selector: Any, labels: Mapping[str, Any]) -> bool:
    """matchLabels only; any other selector shape is treated as not matching."""
    if not isinstance(selector, Mapping) or set(selector) - {"matchLabels"}:
        return False
    match = selector.get("matchLabels") or {}
    return (
        isinstance(match, Mapping)
        and bool(match)
        and all(labels.get(k) == v for k, v in match.items())
    )


def _disruption(deployment: RenderedResource, resources: list[RenderedResource]) -> Evidence:
    namespace, name = _meta(deployment.body)
    replicas = _spec(deployment.body).get("replicas", 1)
    for resource in resources:
        if resource.body.get("kind") != "HorizontalPodAutoscaler":
            continue
        target = _spec(resource.body).get("scaleTargetRef") or {}
        if (
            _meta(resource.body)[0] == namespace
            and isinstance(target, Mapping)
            and (target.get("kind"), target.get("name")) == ("Deployment", name)
        ):
            replicas = _spec(resource.body).get("minReplicas", 1)
    labels = _labels(deployment.body)
    # Flagger serves from a generated <name>-primary Deployment whose pods carry
    # app: <value>-primary, so a budget may select either label set.
    primary = {**labels, "app": f"{labels.get('app')}-primary"} if "app" in labels else labels
    budgets = []
    for resource in resources:
        spec = _spec(resource.body)
        if (
            resource.body.get("kind") == "PodDisruptionBudget"
            and _meta(resource.body)[0] == namespace
            and (_selects(spec.get("selector"), labels) or _selects(spec.get("selector"), primary))
            and (spec.get("minAvailable") or spec.get("maxUnavailable"))
        ):
            budgets.append(_meta(resource.body)[1])
    minimum = replicas if isinstance(replicas, int) and not isinstance(replicas, bool) else 0
    survives = minimum >= 2 and bool(budgets)
    return _evidence(
        EVIDENCE_KIND_DISRUPTION_BUDGET,
        deployment.source_path,
        f"Deployment/{namespace}/{name}/disruption",
        f"{name}: minimum replicas {minimum}; "
        f"{len(budgets)} PodDisruptionBudget(s) select the pods",
        {"minimum_replicas": minimum, "budgets": len(budgets), "survives_drain": survives},
        ("Deployment", namespace, name),
    )


def _pod_security(namespace: str, resources: list[RenderedResource]) -> Evidence | None:
    for resource in resources:
        if resource.body.get("kind") == "Namespace" and _meta(resource.body)[1] == namespace:
            labels = (resource.body.get("metadata") or {}).get("labels") or {}
            level = labels.get("pod-security.kubernetes.io/enforce") if labels else None
            return _evidence(
                EVIDENCE_KIND_POD_SECURITY,
                resource.source_path,
                f"Namespace/{namespace}/pod-security",
                f"application namespace {namespace} enforces Pod Security: {level or 'nothing'}",
                {"enforce_level": str(level or ""), "enforces_restricted": level == "restricted"},
                ("Namespace", namespace),
            )
    return None


def _retention(resource: RenderedResource) -> Evidence:
    namespace, name = _meta(resource.body)
    values = _spec(resource.body).get("values") or {}
    prometheus = values.get("prometheus") if isinstance(values, Mapping) else None
    spec = prometheus.get("prometheusSpec") if isinstance(prometheus, Mapping) else None
    spec = spec if isinstance(spec, Mapping) else {}
    retention, size = spec.get("retention"), spec.get("retentionSize")
    bounded = bool(retention) and bool(size)
    return _evidence(
        EVIDENCE_KIND_METRICS_RETENTION,
        resource.source_path,
        f"HelmRelease/{namespace}/{name}/retention",
        f"{name}: Prometheus retention {retention or 'unset'}, size {size or 'unset'}",
        {"retention_bounded": bounded},
        ("HelmRelease", namespace, name),
    )


_CPU = re.compile(r"^(\d+(?:\.\d+)?)(m?)$")
_MEMORY = re.compile(r"^(\d+(?:\.\d+)?)(Ki|Mi|Gi|K|M|G)?$")
_MIB = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "K": 1000 / 1048576, "M": 1e6 / 1048576}
_MIB["G"] = 1e9 / 1048576


def _cpu(value: Any) -> float:
    match = _CPU.fullmatch(str(value))
    if not match:
        raise ValueError("unparseable CPU quantity")
    return float(match[1]) * (1 if match[2] else 1000)


def _memory(value: Any) -> float:
    match = _MEMORY.fullmatch(str(value))
    if not match:
        raise ValueError("unparseable memory quantity")
    return float(match[1]) * (_MIB[match[2]] if match[2] else 1 / 1048576)


def _requests(node: Any, depth: int = 0) -> list[Mapping[str, Any]]:
    """Every `resources.requests` mapping in HelmRelease values."""
    if depth > 16:
        raise ValueError("values nesting limit reached")
    found: list[Mapping[str, Any]] = []
    if isinstance(node, Mapping):
        resources = node.get("resources")
        if isinstance(resources, Mapping) and isinstance(resources.get("requests"), Mapping):
            found.append(resources["requests"])
        for value in node.values():
            found.extend(_requests(value, depth + 1))
    elif isinstance(node, list):
        for value in node:
            found.extend(_requests(value, depth + 1))
    return found


def _footprint(resources: list[RenderedResource]) -> Evidence:
    cpu = memory = 0.0
    for resource in resources:
        kind = resource.body.get("kind")
        if kind == "HelmRelease":
            blocks = _requests(_spec(resource.body).get("values") or {})
            replicas = 1
        elif kind in _POD_TEMPLATE_KINDS:
            pod = _template(resource.body).get("spec") or {}
            containers = list(pod.get("containers") or []) + list(pod.get("initContainers") or [])
            blocks = [
                (c.get("resources") or {}).get("requests") or {}
                for c in containers
                if isinstance(c, Mapping)
            ]
            count = _spec(resource.body).get("replicas", 1)
            replicas = count if isinstance(count, int) and count > 0 else 1
        else:
            continue
        for block in blocks:
            cpu += _cpu(block.get("cpu", 0)) * replicas
            memory += _memory(block.get("memory", 0)) * replicas
    within = cpu <= _LOCAL_CPU_BUDGET_MILLICORES and memory <= _LOCAL_MEMORY_BUDGET_MIB
    return _evidence(
        EVIDENCE_KIND_DECLARED_FOOTPRINT,
        "k8s/clusters/local",
        f"profile/{_LOCAL_PROFILE}/requests",
        f"Git-declared requests {round(cpu)}m CPU, {round(memory)}Mi memory; "
        f"budget {_LOCAL_CPU_BUDGET_MILLICORES}m, {_LOCAL_MEMORY_BUDGET_MIB}Mi",
        {
            "cpu_millicores": round(cpu),
            "memory_mib": round(memory),
            "within_budget": within,
        },
        ("profile", _LOCAL_PROFILE),
    )


def _reachability(tracked: frozenset[str], reached: set[str]) -> Evidence:
    platform = sorted(
        path
        for path in tracked
        if path.startswith("k8s/")
        and path.endswith((".yaml", ".yml"))
        and not path.startswith(_BOOTSTRAP)
        and not (path.startswith(_APPLICATIONS) and not path.startswith(_PLATFORM_TEMPLATE))
    )
    unreached = [path for path in platform if path not in reached]
    return _evidence(
        EVIDENCE_KIND_MANIFEST_REACHABILITY,
        unreached[0] if unreached else "k8s",
        "platform-manifests",
        f"{len(platform) - len(unreached)} of {len(platform)} platform manifests are reached"
        + (f"; unreached: {', '.join(unreached[:_MAX_SHOWN])}" if unreached else ""),
        {
            "platform_manifests": len(platform),
            "unreached": len(unreached),
            "all_reached": not unreached,
        },
        ("platform-manifests",),
    )


def _load(root: Path, rel_path: str, limits: ExecutionLimits) -> list[Any]:
    path = root / rel_path
    if path.is_symlink() or path.stat().st_size > limits.max_manifest_file_bytes:
        raise ValueError("symlink or oversized")
    return list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def _uses_messaging(document: Any) -> bool:
    if not isinstance(document, Mapping) or document.get("kind") not in _POD_TEMPLATE_KINDS:
        return False
    pod = _template(document).get("spec") or {}
    return any(
        isinstance(env, Mapping) and env.get("name") == "NATS_URL"
        for container in pod.get("containers") or []
        if isinstance(container, Mapping)
        for env in container.get("env") or []
    )


def _messaging(
    root: Path, tracked: frozenset[str], limits: ExecutionLimits
) -> tuple[list[Evidence], int]:
    evidence: list[Evidence] = []
    failures = 0
    apps: dict[str, list[str]] = {}
    for path in sorted(tracked):
        match = _CATALOG_ENTRY.match(path)
        if match and not path.startswith(_PLATFORM_TEMPLATE) and path.endswith((".yaml", ".yml")):
            apps.setdefault(match[1], []).append(path)
    for app, paths in apps.items():
        contract_path = f"{_APPLICATIONS}{app}/fleet-app.yaml"
        try:
            documents = [doc for path in paths for doc in _load(root, path, limits)]
            if not any(_uses_messaging(doc) for doc in documents):
                continue
            data = next(
                (
                    doc.get("data") or {}
                    for doc in _load(root, contract_path, limits)
                    if isinstance(doc, Mapping) and doc.get("kind") == "ConfigMap"
                ),
                {},
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError, AttributeError, TypeError):
            failures += 1
            continue
        prefix = data.get("APP_MESSAGING_PREFIX") if isinstance(data, Mapping) else None
        declared = isinstance(prefix, str) and bool(_MESSAGING_PREFIX.fullmatch(prefix))
        evidence.append(
            _evidence(
                EVIDENCE_KIND_MESSAGING_CONTRACT,
                contract_path,
                f"app/{app}/messaging",
                f"{app} sets NATS_URL; contract channel prefix: {prefix or 'undeclared'}",
                {"declares_prefix": declared},
                ("app", app),
            )
        )
    return evidence, failures


def _dora(
    root: Path, tracked: frozenset[str], limits: ExecutionLimits
) -> tuple[list[Evidence], int]:
    publishers = sorted(path for path in tracked if _PUBLISH_WORKFLOW.match(path))
    if not publishers:
        return [], 0
    try:
        listened: set[str] = set()
        if _DORA_WORKFLOW in tracked:
            [workflow] = _load(root, _DORA_WORKFLOW, limits)
            # YAML 1.1 reads the bare key `on` as True.
            triggers = workflow.get("on") or workflow.get(True) or {}
            names = (triggers.get("workflow_run") or {}).get("workflows") or []
            listened = {str(name) for name in names}
        evidence = []
        for path in publishers:
            [workflow] = _load(root, path, limits)
            name = str(workflow.get("name") or "")
            feeds = name in listened
            evidence.append(
                _evidence(
                    EVIDENCE_KIND_DORA_COVERAGE,
                    path,
                    f"workflow/{path}/dora",
                    f"publish workflow '{name}' "
                    + ("feeds" if feeds else "is not listed in")
                    + " the DORA metrics workflow_run trigger",
                    {"feeds_dora": feeds},
                    ("workflow", path),
                )
            )
        return evidence, 0
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, AttributeError, TypeError):
        return [], 1


def _evaluate(profile: str, resources: list[RenderedResource]) -> tuple[list[Evidence], int]:
    evidence: list[Evidence] = []
    failures = 0
    deployments = _app_deployments(resources)
    for resource in resources:
        try:
            if resource.body.get("kind") == "HelmRelease":
                evidence.append(_helm_recovery(resource))
                chart = ((_spec(resource.body).get("chart") or {}).get("spec") or {}).get("chart")
                if chart == _METRICS_CHART:
                    evidence.append(_retention(resource))
        except (AttributeError, TypeError):
            failures += 1
    for deployment in deployments:
        try:
            evidence.append(_canary(deployment, resources))
            if profile == _AWS_PROFILE:
                evidence.append(_disruption(deployment, resources))
        except (AttributeError, TypeError):
            failures += 1
    for namespace in sorted({_meta(d.body)[0] for d in deployments}):
        item = _pod_security(namespace, resources)
        if item is not None:
            evidence.append(item)
    if profile == _LOCAL_PROFILE:
        try:
            evidence.append(_footprint(resources))
        except (AttributeError, TypeError, ValueError):
            failures += 1
    # One identity per object; conflicting duplicates are withheld.
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.evidence_id] = counts.get(item.evidence_id, 0) + 1
    duplicates = {eid for eid, count in counts.items() if count > 1}
    return [e for e in evidence if e.evidence_id not in duplicates], failures + len(duplicates)


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str],
    tracked_paths: frozenset[str],
) -> CollectorResult:
    reasons: list[str] = []
    visible = frozenset(
        path
        for path in tracked_paths
        if not any(path == ex or path.startswith(f"{ex}/") for ex in excluded_paths)
    )
    clusters = checkout_root / "k8s" / "clusters"
    profiles = (
        sorted(
            d.name
            for d in clusters.iterdir()
            if d.is_dir() and any((d / name).is_file() for name in KUSTOMIZATION_FILES)
        )
        if clusters.is_dir()
        else []
    )
    if len(profiles) > _MAX_PROFILES:
        reasons.append(f"{len(profiles) - _MAX_PROFILES} profile(s) omitted by safety limit")
        profiles = profiles[:_MAX_PROFILES]
    per_profile: dict[str, list[Evidence]] = {}
    reached: set[str] = set()
    failures = 0
    complete = bool(profiles)
    for render in render_profiles(checkout_root, profiles, limits, tracked_paths, excluded_paths):
        reasons.extend(f"{render.profile}: {gap}" for gap in render.gaps)
        complete = complete and render.complete
        reached |= render.read_paths
        per_profile[render.profile], profile_failures = _evaluate(render.profile, render.resources)
        failures += profile_failures
    evidence = list(combine_profiles(per_profile, _PROTECTIVE))
    if not profiles and (checkout_root / "k8s").is_dir():
        reasons.append("no deployment profiles; platform manifests not rendered")
    # An incomplete render may have skipped files it would reach, so an
    # unreached file is only evidence once every profile rendered.
    if complete:
        evidence.append(_reachability(visible, reached))
    for part, part_failures in (
        _messaging(checkout_root, visible, limits),
        _dora(checkout_root, visible, limits),
    ):
        evidence.extend(part)
        failures += part_failures
    if failures:
        reasons.append(f"{failures} resource(s) or file(s) could not be evaluated")
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(
            PLATFORM_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(evidence),
            "; ".join(reasons)[:500] or None,
        ),
    )
