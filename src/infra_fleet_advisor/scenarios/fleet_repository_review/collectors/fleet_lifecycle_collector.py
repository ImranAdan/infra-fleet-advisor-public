import re
import stat
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_FLEET_LIFECYCLE,
    FLEET_LIFECYCLE_COLLECTOR_ID,
    FLEET_LIFECYCLE_COLLECTOR_VERSION,
)

_FACADE_PATH = "fleet"
_LOCAL_STRATEGY_PATH = "scripts/fleet-profiles/local.sh"
_EXPECTED_PROFILES = frozenset({"local", "aws-staging"})
_LIFECYCLE_ACTIONS = frozenset({"setup", "up", "down"})
_SAFE_CASE_VALUE = re.compile(r"^[a-z][a-z0-9-]*$")
_ACTION_ALLOWLIST = re.compile(
    r'^\s*case\s+"\$action"\s+in\s+(?P<values>[a-z0-9|_-]+)\)\s+;;\s+'
    r'\*\)\s+echo\s+"Unknown action:',
    re.MULTILINE,
)
_PROFILE_ALLOWLIST = re.compile(
    r'^\s*case\s+"\$profile"\s+in\s+(?P<values>[a-z0-9|_-]+)\)\s+;;\s+'
    r"\*\)\s+echo\s+'Choose --profile",
    re.MULTILINE,
)
_AWS_STRATEGY = re.compile(
    r'^\s*if\s+\[\s+"\$profile"\s+=\s+aws-staging\s+\];\s+then\s*$'
    r"(?P<body>.*?)"
    r"^\s*fi\s*$",
    re.MULTILINE | re.DOTALL,
)
_LOCAL_MAIN = re.compile(
    r"^\s*local_main\(\)\s*\{\s*$"
    r"(?P<body>.*?)"
    r"^\s*\}\s*$",
    re.MULTILINE | re.DOTALL,
)
_CASE_LABEL = re.compile(r"^\s*(?P<label>[a-z][a-z0-9-]*)\)", re.MULTILINE)
_LOCAL_DISPATCH = re.compile(r'^\s*local_main\s+"\$action"(?:\s|$)', re.MULTILINE)


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _is_excluded(rel_path: str, excluded_paths: frozenset[str]) -> bool:
    return any(
        rel_path == excluded or rel_path.startswith(f"{excluded}/") for excluded in excluded_paths
    )


def _read_bounded_file(
    checkout_root: Path,
    rel_path: str,
    limits: ExecutionLimits,
    tracked_paths: frozenset[str] | None,
) -> tuple[str | None, str | None]:
    path = checkout_root / rel_path
    if not path.exists():
        return None, None
    if tracked_paths is not None and rel_path not in tracked_paths:
        return None, f"{rel_path} is not part of the verified commit"
    try:
        checkout_real = checkout_root.resolve()
        if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
            return None, f"{rel_path} is not a regular in-checkout file"
        if not path.is_file() or path.stat().st_size > limits.max_file_bytes:
            return None, f"{rel_path} is unreadable or exceeds max_file_bytes"
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, f"{rel_path} could not be read as bounded UTF-8 text"


def _values(match: re.Match[str] | None) -> frozenset[str] | None:
    if match is None:
        return None
    values = match.group("values").split("|")
    if not values or any(not _SAFE_CASE_VALUE.fullmatch(value) for value in values):
        return None
    return frozenset(values)


def _case_labels(block: re.Match[str] | None) -> frozenset[str] | None:
    if block is None:
        return None
    return frozenset(match.group("label") for match in _CASE_LABEL.finditer(block.group("body")))


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    if _is_excluded(_FACADE_PATH, excluded_paths) or _is_excluded(
        _LOCAL_STRATEGY_PATH, excluded_paths
    ):
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "lifecycle source excluded by policy",
            ),
        )

    facade, facade_error = _read_bounded_file(checkout_root, _FACADE_PATH, limits, tracked_paths)
    local_strategy, local_error = _read_bounded_file(
        checkout_root, _LOCAL_STRATEGY_PATH, limits, tracked_paths
    )
    errors = tuple(error for error in (facade_error, local_error) if error is not None)
    if errors:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "; ".join(errors),
            ),
        )
    if facade is None:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(FLEET_LIFECYCLE_COLLECTOR_ID, "ok", 0),
        )

    profiles = _values(_PROFILE_ALLOWLIST.search(facade))
    facade_actions = _values(_ACTION_ALLOWLIST.search(facade))
    aws_actions = _case_labels(_AWS_STRATEGY.search(facade))
    local_actions = _case_labels(_LOCAL_MAIN.search(local_strategy or ""))
    if profiles is None or facade_actions is None or aws_actions is None or local_actions is None:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "lifecycle command structure could not be parsed",
            ),
        )
    if profiles != _EXPECTED_PROFILES:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "profile set is outside the registered lifecycle collector scope",
            ),
        )

    try:
        facade_executable = bool((checkout_root / _FACADE_PATH).stat().st_mode & stat.S_IXUSR)
    except OSError:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "fleet mode could not be read",
            ),
        )
    local_dispatch = _LOCAL_DISPATCH.search(facade) is not None
    facade_complete = _LIFECYCLE_ACTIONS <= facade_actions
    local_complete = local_dispatch and _LIFECYCLE_ACTIONS <= local_actions
    aws_complete = _LIFECYCLE_ACTIONS <= aws_actions
    lifecycle_complete = facade_executable and facade_complete and local_complete and aws_complete
    up_down_complete = all(
        action in actions
        for actions in (facade_actions, local_actions, aws_actions)
        for action in ("up", "down")
    )
    evidence = build_evidence(
        collector_id=FLEET_LIFECYCLE_COLLECTOR_ID,
        collector_version=FLEET_LIFECYCLE_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_FLEET_LIFECYCLE,
        source_path=_FACADE_PATH,
        locator="profile lifecycle dispatch",
        excerpt=(
            "setup routed by facade/local/aws-staging: "
            f"{str('setup' in facade_actions).lower()}/"
            f"{str(local_dispatch and 'setup' in local_actions).lower()}/"
            f"{str('setup' in aws_actions).lower()}; "
            f"up/down complete: {str(up_down_complete).lower()}"
        ),
        fact={
            "facade_executable": facade_executable,
            "profiles_are_closed": True,
            "facade_lifecycle_complete": facade_complete,
            "local_lifecycle_complete": local_complete,
            "aws_lifecycle_complete": aws_complete,
            "common_lifecycle_complete": lifecycle_complete,
        },
        identity_parts=("profile-lifecycle-dispatch",),
    )
    return CollectorResult(
        evidence=(evidence,),
        coverage=CollectorCoverage(FLEET_LIFECYCLE_COLLECTOR_ID, "ok", 1),
    )
