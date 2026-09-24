import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    DEPENDENCY_UPDATE_COLLECTOR_ID,
    DEPENDENCY_UPDATE_COLLECTOR_VERSION,
    EVIDENCE_KIND_DEPENDENCY_UPDATES,
)

_CONFIG_PATHS = (".github/dependabot.yml", ".github/dependabot.yaml")
_PINNED_TERRAFORM = re.compile(r"\brequired_providers\b|^\s*version\s*=", re.MULTILINE)
_MAX_EVIDENCE = 200


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _ecosystem(path: str) -> str | None:
    """The Dependabot ecosystem a tracked file's name implies, by closed rule."""
    name = PurePosixPath(path).name
    if path.startswith(".github/workflows/"):
        return "github-actions"
    if name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile"):
        return "docker"
    if re.fullmatch(r"requirements[\w.-]*\.txt|pyproject\.toml|Pipfile", name):
        return "pip"
    if name == "package.json":
        return "npm"
    if name == "go.mod":
        return "gomod"
    if name.endswith(".tf"):
        return "terraform"
    return None


def _manifest_directory(path: str, ecosystem: str) -> str:
    if ecosystem == "github-actions":
        return ""
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _normalise(directory: str) -> str:
    return directory.strip().strip("/")


def _entries(config: Any) -> list[tuple[str, tuple[str, ...], str]]:
    """(ecosystem, directory patterns, interval) for each Dependabot update entry."""
    if not isinstance(config, dict) or not isinstance(config.get("updates"), list):
        raise ValueError("dependabot configuration has no updates list")
    entries = []
    for update in config["updates"]:
        if not isinstance(update, dict) or not isinstance(update.get("package-ecosystem"), str):
            raise ValueError("dependabot update entry is malformed")
        directories = update.get("directories", [update.get("directory")])
        if not isinstance(directories, list) or not all(
            isinstance(item, str) for item in directories
        ):
            raise ValueError("dependabot update entry has no directory")
        schedule = update.get("schedule")
        interval = schedule.get("interval") if isinstance(schedule, dict) else None
        entries.append(
            (
                update["package-ecosystem"],
                tuple(_normalise(item) for item in directories),
                interval if isinstance(interval, str) else "",
            )
        )
    return entries


def _read(checkout_root: Path, rel_path: str, limits: ExecutionLimits) -> str:
    path = checkout_root / rel_path
    if path.is_symlink() or not path.resolve().is_relative_to(checkout_root.resolve()):
        raise ValueError(f"{rel_path} is not a regular in-checkout file")
    if path.stat().st_size > limits.max_file_bytes:
        raise ValueError(f"{rel_path} exceeds max_file_bytes")
    return path.read_text(encoding="utf-8")


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    """Pair every tracked dependency manifest directory with a Dependabot entry.

    Only file names from the verified commit are classified; Terraform files
    are read solely to skip local modules that pin nothing Dependabot updates."""
    if tracked_paths is None:
        tracked_paths = frozenset(
            path.relative_to(checkout_root).as_posix()
            for path in checkout_root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(checkout_root).parts
        )
    eligible = sorted(
        path
        for path in tracked_paths
        if not any(path == ex or path.startswith(f"{ex}/") for ex in excluded_paths)
        and ".terraform" not in PurePosixPath(path).parts
    )
    failures = 0
    config_path = next((path for path in _CONFIG_PATHS if path in eligible), None)
    entries: list[tuple[str, tuple[str, ...], str]] = []
    if config_path is not None:
        try:
            entries = _entries(yaml.safe_load(_read(checkout_root, config_path, limits)))
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
            return CollectorResult(
                (),
                CollectorCoverage(
                    DEPENDENCY_UPDATE_COLLECTOR_ID,
                    "partial",
                    0,
                    f"dependabot configuration could not be evaluated: {type(error).__name__}",
                ),
            )

    manifests: dict[tuple[str, str], str] = {}
    for path in eligible:
        ecosystem = _ecosystem(path)
        if ecosystem is None:
            continue
        if ecosystem == "terraform":
            try:
                if not _PINNED_TERRAFORM.search(_read(checkout_root, path, limits)):
                    continue
            except (OSError, UnicodeError, ValueError):
                failures += 1
                continue
        manifests.setdefault((ecosystem, _manifest_directory(path, ecosystem)), path)

    evidence = []
    for (ecosystem, directory), source_path in sorted(manifests.items())[:_MAX_EVIDENCE]:
        intervals = [
            interval
            for entry_ecosystem, patterns, interval in entries
            if entry_ecosystem == ecosystem
            and any(directory == pattern or fnmatch(directory, pattern) for pattern in patterns)
        ]
        shown = directory or "/"
        evidence.append(
            build_evidence(
                collector_id=DEPENDENCY_UPDATE_COLLECTOR_ID,
                collector_version=DEPENDENCY_UPDATE_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_DEPENDENCY_UPDATES,
                source_path=source_path,
                locator=f"{ecosystem}:{shown}",
                excerpt=(
                    f"{ecosystem} manifests in {shown}: "
                    + (f"Dependabot {intervals[0]}" if intervals else "no Dependabot entry")
                ),
                fact={
                    "covered_by_dependabot": bool(intervals),
                    "interval": intervals[0] if intervals else "",
                },
                identity_parts=(ecosystem, shown),
            )
        )

    reasons = []
    if failures:
        reasons.append(f"{failures} Terraform file(s) could not be read")
    if len(manifests) > _MAX_EVIDENCE:
        reasons.append("manifest directories omitted by safety limit")
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(
            DEPENDENCY_UPDATE_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(evidence),
            "; ".join(reasons) or None,
        ),
    )
