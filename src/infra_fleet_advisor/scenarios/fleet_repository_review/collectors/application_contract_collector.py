"""Whether the fleet's platform is coupled to a specific application.

The fleet selects its application through a contract ConfigMap,
`k8s/fleet-app/fleet-app.yaml`, and every application ships its own copy under
`k8s/applications/<name>/fleet-app.yaml`. The platform is everything that runs
any application: Kubernetes manifests outside the applications' own
directories, the lifecycle scripts, policies and local platform files.

This collector reads the contracts, searches the tracked platform files for any
application name as a whole word, and requires the application references on
platform Canary, HPA, NetworkPolicy, Ingress and HTTPRoute objects to come from
`${APP_NAME}`. A new literal binding is therefore caught as well as a known
name. Files are read as text; nothing is executed.

It can show coupling but cannot prove its absence: a script could name an
application no contract declares. An unreadable, oversized or excluded contract
leaves the verdict unknown unless readable evidence already shows coupling.
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
}
_APP_NAMESPACE = "applications"


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _app_name(text: str) -> str | None:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    data = document.get("data") if isinstance(document, dict) else None
    name = data.get("APP_NAME") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


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


def _literal_bound_object(text: str) -> bool | None:
    """True if an app-bound object has a literal binding."""
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    for document in documents:
        if not isinstance(document, dict) or document.get("kind") not in _APP_BOUND_FIELDS:
            continue
        metadata = document.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("namespace") != _APP_NAMESPACE:
            continue
        for path in _APP_BOUND_FIELDS[document["kind"]]:
            values = _values_at(document, path)
            if values and any(
                not isinstance(value, str) or "${APP_NAME}" not in value for value in values
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
    apps: set[str] = set()
    for rel_path in contract_paths:
        text = read(rel_path)
        name = _app_name(text) if text is not None else None
        match = _APP_CONTRACT.match(rel_path)
        if name is None or match is None or name != match.group(1):
            failures += text is not None  # read() already counted a failed read
            contract_unknown = True
            continue
        apps.add(name)

    selected = None
    if SELECTED_CONTRACT in tracked:
        text = read(SELECTED_CONTRACT)
        selected = _app_name(text) if text is not None else None
        if selected is None:
            failures += text is not None
            contract_unknown = True

    platform = sorted(p for p in tracked if _is_platform(p, app_directories))
    truncated = len(platform) > _MAX_PLATFORM_FILES
    pattern = (
        re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in sorted(apps)) + r")(?![\w-])")
        if apps
        else None
    )
    mentions: list[str] = []
    literal: list[str] = []
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

    coupled = mentions + [path for path in literal if path not in mentions]
    contract_present = selected is not None and selected in apps
    fact: dict[str, bool | int] = {
        "contract_present": contract_present,
        "application_count": len(apps),
        "platform_files_naming_an_app": len(mentions),
        "platform_objects_with_literal_bindings": len(literal),
    }
    # Readable coupling decides on its own; otherwise an unknown contract
    # leaves the verdict out, so no recommendation rests on unseen input.
    if coupled or not contract_unknown:
        fact["swappable"] = contract_present and len(apps) >= 2 and not coupled

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
    excerpt = f"selected={selected or 'none'}; apps={','.join(sorted(apps)) or 'none'}; " + (
        f"{len(mentions)} platform file(s) name an app, {len(literal)} bind one literally; "
        f"first {coupled[0]}"
        if coupled
        else "no platform file names or literally binds an app"
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
    ]
    return CollectorResult(
        (evidence,),
        CollectorCoverage(
            APP_CONTRACT_COLLECTOR_ID,
            "partial" if failures or truncated else "ok",
            1,
            "; ".join(r for r in reasons if r) or None,
        ),
    )
