"""Whether the fleet's platform is coupled to a specific application.

The fleet selects its application through a contract ConfigMap,
`k8s/fleet-app/fleet-app.yaml`, and every application ships its own copy under
`k8s/applications/<name>/fleet-app.yaml`. The platform is everything that runs
any application: Kubernetes manifests outside the applications' own
directories, the lifecycle scripts, policies and local platform files.

This collector reads the contracts, searches the tracked platform files for any
application name as a whole word, and requires the application references on
platform Canary, HPA, application-selecting NetworkPolicy, Ingress and
HTTPRoute objects to come from `${APP_NAME}`. A namespace-wide NetworkPolicy
with an empty pod selector is a platform boundary rather than an application
binding. A new literal binding is therefore caught as well as a known name.
Files are read as text; nothing is executed.

Absence is provable only over a known set of applications, so every
application source directory `applications/<name>/` must have a contract, and
the selection kustomization must include exactly the selected app. Anything
the scan cannot resolve (an uncontracted source, an unreadable, oversized or
excluded file, an object without a literal namespace, an unresolved patch)
makes coverage partial and leaves the verdict unknown unless readable evidence
already shows coupling. A declared on-demand launcher (non-Flux RBAC that can
create workloads or Flux deployers) also keeps coverage partial: M-004's launch
constraints are run-time behaviour this text scan cannot see.
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    APP_CONTRACT_COLLECTOR_ID,
    APP_CONTRACT_COLLECTOR_VERSION,
    EVIDENCE_KIND_APPLICATION_COUPLING,
)

SELECTED_CONTRACT = "k8s/fleet-app/fleet-app.yaml"
_APP_CONTRACT = re.compile(r"^k8s/applications/([a-z0-9][-a-z0-9]*)/fleet-app\.yaml$")
_SELECTION = "k8s/applications/kustomization.yaml"
_PLATFORM_ROOTS = ("k8s/", "scripts/", "policies/", "platform/")
_PLATFORM_FILES = ("fleet", ".github/workflows/local-kubernetes.yml")
# A text search is cheap, so this scan has its own bound, like the renderer's
# source scan, rather than the per-collector manifest limit.
_MAX_PLATFORM_FILES = 1000
# Platform objects that act on the application, so their identity and target
# references must come from the contract. Controllers' own objects elsewhere
# (Flux's NetworkPolicies, for example) are not app-bound.
_APP_BOUND_FIELDS = {
    "Canary": (
        ("metadata", "name"),
        ("spec", "targetRef", "name"),
        ("spec", "autoscalerRef", "name"),
    ),
    "HorizontalPodAutoscaler": (
        ("metadata", "name"),
        ("spec", "scaleTargetRef", "name"),
    ),
    "NetworkPolicy": (("metadata", "name"),),
    "Ingress": (
        ("metadata", "name"),
        ("spec", "defaultBackend", "service", "name"),
        ("spec", "rules", "*", "http", "paths", "*", "backend", "service", "name"),
    ),
    "HTTPRoute": (
        ("metadata", "name"),
        ("spec", "rules", "*", "backendRefs", "*", "name"),
    ),
    # A workload the platform itself places in the applications namespace is
    # an application of its own unless the contract names it.
    **dict.fromkeys(
        (
            "Deployment",
            "StatefulSet",
            "DaemonSet",
            "ReplicaSet",
            "Job",
            "CronJob",
            "Pod",
            "Service",
            "HelmRelease",
        ),
        (("metadata", "name"),),
    ),
}
_APP_NAMESPACE = "applications"
# RBAC that lets an identity create workloads, or the Flux objects that deploy
# them, declares an on-demand launcher. Flux's own bundle is excluded.
_LAUNCH_RESOURCES = frozenset(
    {
        "*",
        "kustomizations",
        "helmreleases",
        "deployments",
        "statefulsets",
        "daemonsets",
        "replicasets",
        "jobs",
        "cronjobs",
        "pods",
    }
)
_BROAD_ROLES = frozenset({"cluster-admin", "admin", "edit"})


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _contract_data(text: str) -> dict[object, object] | None:
    """A contract's data, or None when it names no application."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    data = document.get("data") if isinstance(document, dict) else None
    name = data.get("APP_NAME") if isinstance(data, dict) else None
    return data if isinstance(data, dict) and isinstance(name, str) and name else None


def _selected_directories(text: str) -> list[str] | None:
    """The local directories the selection kustomization includes."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    resources = document.get("resources") if isinstance(document, dict) else None
    if not isinstance(resources, list):
        return None
    names = [r.removeprefix("./").rstrip("/") if isinstance(r, str) else "" for r in resources]
    # Anything but a sibling directory could include an app this scan cannot see.
    return names if all(re.fullmatch(r"[a-z0-9][-a-z0-9]*", n) for n in names) else None


def _is_platform(rel_path: str, app_directories: set[str]) -> bool:
    if rel_path in (SELECTED_CONTRACT, _SELECTION):
        return False
    if any(rel_path.startswith(f"k8s/applications/{app}/") for app in app_directories):
        return False
    return rel_path in _PLATFORM_FILES or rel_path.startswith(_PLATFORM_ROOTS)


def _values_at(value: object, path: tuple[str, ...]) -> list[object]:
    if not path:
        return [value]
    head, *tail = path
    if head == "*":
        if not isinstance(value, list):
            return []
        return [item for entry in value for item in _values_at(entry, tuple(tail))]
    if not isinstance(value, dict) or head not in value:
        return []
    return _values_at(value[head], tuple(tail))


def _namespace_wide_policy(document: dict[object, object]) -> bool:
    """Whether a NetworkPolicy selector names every pod in its namespace."""
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return False
    selector = spec.get("podSelector")
    if not isinstance(selector, dict) or not set(selector) <= {
        "matchLabels",
        "matchExpressions",
    }:
        return False
    labels = selector.get("matchLabels", {})
    expressions = selector.get("matchExpressions", [])
    return (
        isinstance(labels, dict)
        and not labels
        and isinstance(expressions, list)
        and not expressions
    )


def _bound_document(document: dict[object, object]) -> bool | None:
    """True if an app-bound object binds literally; None if unresolvable."""
    kind = document.get("kind")
    if kind not in _APP_BOUND_FIELDS:
        return False
    metadata = document.get("metadata")
    spec = document.get("spec")
    namespace = metadata.get("namespace") if isinstance(metadata, dict) else None
    if kind == "HelmRelease" and isinstance(spec, dict) and "targetNamespace" in spec:
        namespace = spec["targetNamespace"]
    if not isinstance(namespace, str):
        # Its namespace comes from an overlay this text search cannot resolve.
        return None
    if namespace != _APP_NAMESPACE:
        return False
    # An empty selector covers every pod in the namespace. Its identity is
    # platform policy, not an application reference, so requiring its name
    # to vary with APP_NAME would create coupling rather than detect it.
    if kind == "NetworkPolicy" and _namespace_wide_policy(document):
        return False
    for path in _APP_BOUND_FIELDS[str(kind)]:
        values = _values_at(document, path)
        if values and any(
            not isinstance(value, str) or "${APP_NAME}" not in value for value in values
        ):
            return True
    return False


def _segments_match(pointer: list[str], field: tuple[str, ...]) -> bool:
    return all(
        part == key or (key == "*" and (part.isdigit() or part == "-"))
        for part, key in zip(pointer, field, strict=False)
    )


def _bound_patch(entry: object) -> bool | None:
    """Whether a kustomize patch sets an app-bound field literally."""
    if not isinstance(entry, dict) or not isinstance(entry.get("patch"), str):
        return None  # a patch file or unknown shape
    target = entry.get("target")
    kind = target.get("kind") if isinstance(target, dict) else None
    if kind is not None and kind not in _APP_BOUND_FIELDS:
        return False
    fields = [
        field
        for bound_kind, kind_fields in _APP_BOUND_FIELDS.items()
        if kind in (None, bound_kind)
        for field in kind_fields
    ]
    try:
        operations = yaml.safe_load(entry["patch"])
    except yaml.YAMLError:
        return None
    if not isinstance(operations, list):
        return None  # a strategic-merge patch
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("path"), str):
            return None
        if operation.get("op") in ("remove", "test"):
            continue
        stripped = operation["path"].strip("/")
        pointer = stripped.split("/") if stripped else []
        touched = [field for field in fields if _segments_match(pointer, field)]
        if not touched:
            continue
        value = operation.get("value")
        if operation.get("op") not in ("add", "replace") or not any(
            len(field) == len(pointer) for field in touched
        ):
            return None  # moves, copies and subtree writes are not resolved
        if not isinstance(value, str) or "${APP_NAME}" not in value:
            return True
    return False


def _literal_bound_object(text: str) -> bool | None:
    """True if an app-bound object or patch binds literally; None if unknown."""
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    states: list[bool | None] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        states.append(_bound_document(document))
        # kustomization.yaml may omit its kind, so its patch keys identify it.
        if "patchesJson6902" in document or "patchesStrategicMerge" in document:
            states.append(None)
        if document.get("kind") == "Kustomization" or "patches" in document:
            spec = document.get("spec")
            for owner in (document, spec if isinstance(spec, dict) else {}):
                patches = owner.get("patches", [])
                entries = patches if isinstance(patches, list) else [None]
                states.extend(_bound_patch(entry) for entry in entries)
    if True in states:
        return True
    return None if None in states else False


def _declares_launcher(text: str) -> bool:
    """Whether non-Flux RBAC lets an identity create workloads or Flux deployers."""
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return False  # already counted as unreadable by the binding scan
    for document in documents:
        if not isinstance(document, dict):
            continue
        metadata = document.get("metadata")
        labels = metadata.get("labels") if isinstance(metadata, dict) else None
        if isinstance(labels, dict) and labels.get("app.kubernetes.io/part-of") == "flux":
            continue
        kind = document.get("kind")
        if kind in ("RoleBinding", "ClusterRoleBinding"):
            role_ref = document.get("roleRef")
            if isinstance(role_ref, dict) and role_ref.get("name") in _BROAD_ROLES:
                return True
        if kind not in ("Role", "ClusterRole"):
            continue
        rules = document.get("rules")
        for rule in rules if isinstance(rules, list) else []:
            if not isinstance(rule, dict):
                continue
            resources = rule.get("resources")
            verbs = rule.get("verbs")
            if (
                isinstance(resources, list)
                and isinstance(verbs, list)
                and _LAUNCH_RESOURCES.intersection(resources)
                and {"create", "*"}.intersection(verbs)
            ):
                return True
    return False


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    """One record: is the platform coupled to a specific application?"""
    checkout_real = checkout_root.resolve()
    tracked = (
        tracked_paths
        if tracked_paths is not None
        else frozenset(
            p.relative_to(checkout_root).as_posix()
            for p in checkout_root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(checkout_root).parts
        )
    )
    # Without an applications tree there is no app to couple to: no evidence,
    # so the position stays unverified rather than divergent.
    if not any(p.startswith("k8s/applications/") for p in tracked):
        return CollectorResult((), CollectorCoverage(APP_CONTRACT_COLLECTOR_ID, "ok", 0))

    failures = 0
    contract_unknown = False

    def read(rel_path: str) -> str | None:
        nonlocal failures
        path = checkout_root / rel_path
        if any(rel_path == ex or rel_path.startswith(f"{ex}/") for ex in excluded_paths):
            failures += 1
            return None
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                raise ValueError("not a regular in-checkout file")
            # Platform files are manifests (the Flux controller bundle is
            # ~500 KB), so the manifest size bound applies.
            if path.stat().st_size > limits.max_manifest_file_bytes:
                raise ValueError("file exceeds max_manifest_file_bytes")
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            failures += 1
            return None

    contract_paths = sorted(p for p in tracked if _APP_CONTRACT.match(p))
    app_directories = {
        match.group(1)
        for rel_path in contract_paths
        if (match := _APP_CONTRACT.match(rel_path)) is not None
    }
    contracts: dict[str, dict[object, object]] = {}
    for rel_path in contract_paths:
        text = read(rel_path)
        data = _contract_data(text) if text is not None else None
        match = _APP_CONTRACT.match(rel_path)
        if data is None or match is None or data["APP_NAME"] != match.group(1):
            failures += text is not None  # read() already counted a failed read
            contract_unknown = True
            continue
        contracts[match.group(1)] = data
    apps = set(contracts)
    # The name search is complete only if every application the fleet ships
    # (its source under applications/<name>/) has a contract naming it.
    uncontracted = sorted(
        {p.split("/")[1] for p in tracked if p.startswith("applications/") and p.count("/") >= 2}
        - app_directories
    )
    contract_unknown |= bool(uncontracted)

    selected = None
    selected_data = None
    if SELECTED_CONTRACT in tracked:
        text = read(SELECTED_CONTRACT)
        selected_data = _contract_data(text) if text is not None else None
        selected = str(selected_data["APP_NAME"]) if selected_data is not None else None
        if selected is None:
            failures += text is not None
            contract_unknown = True

    # The selection is one value: the kustomization includes exactly the app
    # the contract names, and the contract is that app's own, unchanged.
    selection_text = read(_SELECTION) if _SELECTION in tracked else None
    included = _selected_directories(selection_text) if selection_text is not None else None
    if included is None:
        failures += selection_text is not None or _SELECTION not in tracked
        contract_unknown = True
    selection_consistent = (
        included is not None
        and selected is not None
        and [name for name in included if name in app_directories] == [selected]
        and contracts.get(selected) == selected_data
    )

    platform = sorted(p for p in tracked if _is_platform(p, app_directories))
    truncated = len(platform) > _MAX_PLATFORM_FILES
    pattern = (
        re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in sorted(apps)) + r")(?![\w-])")
        if apps
        else None
    )
    mentions: list[str] = []
    literal: list[str] = []
    launcher = False
    for rel_path in platform[:_MAX_PLATFORM_FILES]:
        text = read(rel_path)
        if text is None:
            continue
        if pattern is not None and pattern.search(text):
            mentions.append(rel_path)
        if rel_path.startswith("k8s/") and rel_path.endswith((".yaml", ".yml")):
            bound = _literal_bound_object(text)
            if bound is None:
                failures += 1
            elif bound:
                literal.append(rel_path)
            launcher = launcher or _declares_launcher(text)

    coupled = mentions + [path for path in literal if path not in mentions]
    contract_present = selected is not None and selected in apps
    fact: dict[str, bool | int] = {
        "contract_present": contract_present,
        "application_count": len(apps),
        "platform_files_naming_an_app": len(mentions),
        "platform_objects_with_literal_bindings": len(literal),
        "selection_consistent": selection_consistent,
        "uncontracted_application_sources": len(uncontracted),
        "on_demand_launcher": launcher,
    }
    # Readable coupling decides on its own; otherwise an unknown contract
    # leaves the verdict out, so no recommendation rests on unseen input.
    if coupled or not contract_unknown:
        fact["swappable"] = (
            contract_present and len(apps) >= 2 and not coupled and selection_consistent
        )

    candidates = [
        *coupled,
        SELECTED_CONTRACT,
        _SELECTION,
        *sorted(f"k8s/applications/{app}/fleet-app.yaml" for app in apps),
    ]
    anchor = next(
        (path for path in candidates if path in tracked),
        min(p for p in tracked if p.startswith("k8s/applications/")),
    )
    excerpt = (
        f"selected={selected or 'none'}; apps={','.join(sorted(apps)) or 'none'}; "
        + (
            f"{len(mentions)} platform file(s) name an app, {len(literal)} bind one literally; "
            f"first {coupled[0]}"
            if coupled
            else "no platform file names or literally binds an app"
        )
        + ("" if selection_consistent else "; selection does not match the contract")
    )
    evidence = build_evidence(
        collector_id=APP_CONTRACT_COLLECTOR_ID,
        collector_version=APP_CONTRACT_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_APPLICATION_COUPLING,
        source_path=anchor,
        locator=f"platform application coupling ({PurePosixPath(anchor).name})",
        excerpt=excerpt[:280],
        fact=fact,
        identity_parts=("platform", "application coupling"),
    )
    reasons = [
        f"{failures} contract or platform file(s) could not be read" if failures else "",
        "platform files omitted by safety limit" if truncated else "",
        f"application source(s) without a contract: {', '.join(uncontracted)}"
        if uncontracted
        else "",
        # M-004 constrains what an on-demand launch does at run time: its
        # revision, identity and teardown. Repository text cannot prove those.
        "an on-demand application launcher is declared; its run-time constraints "
        "are outside repository evidence"
        if launcher
        else "",
    ]
    incomplete = failures or truncated or uncontracted or launcher
    return CollectorResult(
        (evidence,),
        CollectorCoverage(
            APP_CONTRACT_COLLECTOR_ID,
            "partial" if incomplete else "ok",
            1,
            "; ".join(r for r in reasons if r) or None,
        ),
    )
