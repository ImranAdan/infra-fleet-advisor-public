"""Whether the fleet's platform names an application of its own.

The fleet selects its application through a contract ConfigMap,
`k8s/fleet-app/fleet-app.yaml`, and every application ships its own copy under
`k8s/applications/<name>/fleet-app.yaml`. The platform is everything that runs
any application: Kubernetes manifests outside the applications' own
directories, the lifecycle scripts, policies and local platform files. This
collector reads the contracts and searches those tracked platform files for any
application name as a whole word. Files are read as text; nothing is executed.
An unreadable, oversized or omitted file makes coverage partial, so a name it
could not see never looks like a clean platform.
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
_PLATFORM_FILES = ("fleet",)
# A text search is cheap, so this scan has its own bound, like the renderer's
# source scan, rather than the per-collector manifest limit.
_MAX_PLATFORM_FILES = 1000


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _app_name(text: str) -> str | None:
    document = yaml.safe_load(text)
    data = document.get("data") if isinstance(document, dict) else None
    name = data.get("APP_NAME") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def _is_platform(rel_path: str, apps: set[str]) -> bool:
    if rel_path in (SELECTED_CONTRACT, _SELECTION):
        return False
    if any(rel_path.startswith(f"k8s/applications/{app}/") for app in apps):
        return False
    return rel_path in _PLATFORM_FILES or rel_path.startswith(_PLATFORM_ROOTS)


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    """One record: is the application a plug-in the platform never names?"""
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

    apps: set[str] = set()
    for rel_path in sorted(p for p in tracked if _APP_CONTRACT.match(p)):
        text = read(rel_path)
        try:
            name = _app_name(text) if text is not None else None
        except yaml.YAMLError:
            name = None
        match = _APP_CONTRACT.match(rel_path)
        if name is None or match is None or name != match.group(1):
            failures += 1
            continue
        apps.add(name)

    selected = None
    if SELECTED_CONTRACT in tracked:
        text = read(SELECTED_CONTRACT)
        try:
            selected = _app_name(text) if text is not None else None
        except yaml.YAMLError:
            failures += 1

    platform = sorted(p for p in tracked if _is_platform(p, apps))
    truncated = len(platform) > _MAX_PLATFORM_FILES
    mentions: list[str] = []
    if apps:
        pattern = re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(app) for app in sorted(apps)) + r")(?![\w-])"
        )
        for rel_path in platform[:_MAX_PLATFORM_FILES]:
            text = read(rel_path)
            if text is not None and pattern.search(text):
                mentions.append(rel_path)

    contract_present = selected is not None and selected in apps
    swappable = contract_present and len(apps) >= 2 and not mentions
    anchor = mentions[0] if mentions else SELECTED_CONTRACT
    named = PurePosixPath(anchor).name
    excerpt = f"selected={selected or 'none'}; apps={','.join(sorted(apps)) or 'none'}; " + (
        f"{len(mentions)} platform file(s) name an app, first {anchor}"
        if mentions
        else "no platform file names an app"
    )
    evidence = build_evidence(
        collector_id=APP_CONTRACT_COLLECTOR_ID,
        collector_version=APP_CONTRACT_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_APPLICATION_COUPLING,
        source_path=anchor if (checkout_root / anchor).exists() else SELECTED_CONTRACT,
        locator=f"platform application coupling ({named})",
        excerpt=excerpt[:280],
        fact={
            "contract_present": contract_present,
            "application_count": len(apps),
            "platform_files_naming_an_app": len(mentions),
            "swappable": swappable,
        },
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
