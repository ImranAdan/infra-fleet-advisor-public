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
_STRATEGY_PATHS = {
    "local": "scripts/fleet-profiles/local.sh",
    "aws-staging": "scripts/fleet-profiles/aws-staging.sh",
}
_EXPECTED_PROFILES = frozenset(_STRATEGY_PATHS)
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
_STRATEGY_SELECTION = re.compile(
    r'^\s*case\s+"\$profile"\s+in\s*$'
    r"(?P<body>.*?)"
    r"^\s*esac\s*$",
    re.MULTILINE | re.DOTALL,
)
_STRATEGY_SOURCE = re.compile(
    r'^\s*(?P<profile>[a-z][a-z0-9-]*)\)\s+source\s+"\$fleet_root/'
    r'(?P<path>scripts/fleet-profiles/[a-z][a-z0-9-]*\.sh)"\s+;;\s*$',
    re.MULTILINE,
)
_PROFILE_MAIN = re.compile(
    r"^\s*profile_main\(\)\s*\{\s*$"
    r"(?P<body>.*?)"
    r"^\s*\}\s*$",
    re.MULTILINE | re.DOTALL,
)
_CASE_LABEL = re.compile(r"^\s*(?P<label>[a-z][a-z0-9-]*)\)", re.MULTILINE)
_PROFILE_DISPATCH = re.compile(
    r'^\s*profile_main\s+"\$action"\s+"\$revision"\s+"\$service"\s+"\$apply"\s*$',
    re.MULTILINE,
)
_LOCAL_TOOL_INSTALL = re.compile(
    r'^\s*"\$fleet_root/scripts/install-profile-tools\.sh"\s+'
    r'"\$FLEET_STATE/bin"\s+--local\s*$',
    re.MULTILINE,
)
_LOCAL_TOOL_PATH = re.compile(r'^\s*export\s+PATH="\$FLEET_STATE/bin:\$PATH"\s*$', re.MULTILINE)
_LOCAL_GIT_STATE = re.compile(
    r"git\s+rev-parse\s+--path-format=absolute\s+--git-common-dir.*?"
    r'^\s*FLEET_STATE="\$common_dir/fleet/local"\s*$',
    re.MULTILINE | re.DOTALL,
)
_LOCAL_KUBECTL_CONTEXT = re.compile(
    r'kubectl\s+--kubeconfig\s+"\$FLEET_STATE/kubeconfig"\s+'
    r'--context\s+"\$FLEET_CONTEXT"'
)
_LOCAL_FLUX_CONTEXT = re.compile(
    r'flux\s+--kubeconfig\s+"\$FLEET_STATE/kubeconfig"\s+'
    r'--context\s+"\$FLEET_CONTEXT"'
)
_LOCAL_NEXT_COMMAND = re.compile(r"Next:\s+\./fleet up --profile local")
_AWS_ONBOARDING_PATH = "scripts/onboard-aws-profile.sh"
_AWS_SETUP_PLAN_ROUTE = re.compile(
    r'^\s*exec\s+"\$fleet_root/scripts/onboard-aws-profile\.sh"\s+plan\s*;;\s*$', re.MULTILINE
)
_AWS_PLAN_DEFAULT = re.compile(r"^mode=\$\{1:-plan\}\s*$", re.MULTILINE)
_AWS_TARGET_REPORTS = (
    re.compile(r'^echo\s+"AWS target:', re.MULTILINE),
    re.compile(r'^echo\s+"GitHub target:', re.MULTILINE),
)
_AWS_SECRET_FROM_STDIN = re.compile(r"\|\s*gh\s+secret\s+set\s")
_AWS_SECRET_IN_ARGV = re.compile(r"gh\s+secret\s+set\b[^\n]*--body")
_AWS_NEXT_COMMAND = re.compile(r"Next:\s+\./fleet up --profile aws-staging")
# The teardown workflow asks a human to type its target. A strategy that types
# it for them turns that gate into a formality.
_AWS_TEARDOWN_AUTOCONFIRM = re.compile(r"confirm_destroy=destroy staging")


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


def _strategy_sources(facade: str) -> dict[str, str] | None:
    selection = _STRATEGY_SELECTION.search(facade)
    if selection is None:
        return None
    mappings = tuple(
        (match.group("profile"), match.group("path"))
        for match in _STRATEGY_SOURCE.finditer(selection.group("body"))
    )
    if len(mappings) != len(dict(mappings)):
        return None
    return dict(mappings)


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    lifecycle_paths = (_FACADE_PATH, *_STRATEGY_PATHS.values(), _AWS_ONBOARDING_PATH)
    if any(_is_excluded(path, excluded_paths) for path in lifecycle_paths):
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
    strategy_sources: dict[str, str | None] = {}
    strategy_errors: list[str] = []
    for profile, path in _STRATEGY_PATHS.items():
        source, error = _read_bounded_file(checkout_root, path, limits, tracked_paths)
        strategy_sources[profile] = source
        if error is not None:
            strategy_errors.append(error)
    onboarding, onboarding_error = _read_bounded_file(
        checkout_root, _AWS_ONBOARDING_PATH, limits, tracked_paths
    )
    errors = tuple(
        error for error in (facade_error, *strategy_errors, onboarding_error) if error is not None
    )
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

    if any(source is None for source in strategy_sources.values()):
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "lifecycle strategy file is missing",
            ),
        )

    profiles = _values(_PROFILE_ALLOWLIST.search(facade))
    facade_actions = _values(_ACTION_ALLOWLIST.search(facade))
    selected_strategies = _strategy_sources(facade)
    profile_dispatch = _PROFILE_DISPATCH.search(facade) is not None
    strategy_actions = {
        profile: _case_labels(_PROFILE_MAIN.search(source or ""))
        for profile, source in strategy_sources.items()
    }
    if (
        profiles is None
        or facade_actions is None
        or selected_strategies is None
        or any(actions is None for actions in strategy_actions.values())
    ):
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
    if selected_strategies != _STRATEGY_PATHS or not profile_dispatch:
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                FLEET_LIFECYCLE_COLLECTOR_ID,
                "partial",
                0,
                "profile strategy selection is outside the registered lifecycle contract",
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
    facade_complete = _LIFECYCLE_ACTIONS <= facade_actions
    local_complete = _LIFECYCLE_ACTIONS <= (strategy_actions["local"] or frozenset())
    aws_complete = _LIFECYCLE_ACTIONS <= (strategy_actions["aws-staging"] or frozenset())
    lifecycle_complete = facade_executable and facade_complete and local_complete and aws_complete
    local_source = strategy_sources["local"] or ""
    local_installs_pinned_tools = _LOCAL_TOOL_INSTALL.search(local_source) is not None
    local_uses_checkout_state = (
        _LOCAL_GIT_STATE.search(local_source) is not None
        and len(_LOCAL_TOOL_PATH.findall(local_source)) >= 2
    )
    local_uses_explicit_context = (
        _LOCAL_KUBECTL_CONTEXT.search(local_source) is not None
        and _LOCAL_FLUX_CONTEXT.search(local_source) is not None
    )
    local_prints_next_command = _LOCAL_NEXT_COMMAND.search(local_source) is not None
    local_first_use_complete = all(
        (
            local_installs_pinned_tools,
            local_uses_checkout_state,
            local_uses_explicit_context,
            local_prints_next_command,
        )
    )
    aws_source = strategy_sources["aws-staging"] or ""
    onboarding = onboarding or ""
    aws_setup_plans_by_default = (
        _AWS_SETUP_PLAN_ROUTE.search(aws_source) is not None
        and _AWS_PLAN_DEFAULT.search(onboarding) is not None
    )
    aws_setup_reports_targets = all(
        pattern.search(onboarding) is not None for pattern in _AWS_TARGET_REPORTS
    )
    aws_secrets_from_stdin = (
        _AWS_SECRET_FROM_STDIN.search(onboarding) is not None
        and _AWS_SECRET_IN_ARGV.search(onboarding) is None
    )
    aws_prints_next_command = _AWS_NEXT_COMMAND.search(onboarding) is not None
    aws_teardown_operator_confirmed = _AWS_TEARDOWN_AUTOCONFIRM.search(aws_source) is None
    aws_onboarding_complete = all(
        (
            aws_complete,
            aws_setup_plans_by_default,
            aws_setup_reports_targets,
            aws_secrets_from_stdin,
            aws_prints_next_command,
            aws_teardown_operator_confirmed,
        )
    )

    # One record per check. Checks resolve and regress independently, and a
    # report keys evidence by ID: a shared ID would let a new finding's current
    # facts overwrite the historical facts a resolved finding still cites.
    def record(
        identity: str, source_path: str, locator: str, excerpt: str, fact: dict[str, bool]
    ) -> Evidence:
        return build_evidence(
            collector_id=FLEET_LIFECYCLE_COLLECTOR_ID,
            collector_version=FLEET_LIFECYCLE_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_FLEET_LIFECYCLE,
            source_path=source_path,
            locator=locator,
            excerpt=excerpt,
            fact=fact,
            identity_parts=(identity,),
        )

    evidence = (
        record(
            "profile-lifecycle-dispatch",
            _FACADE_PATH,
            "profile lifecycle dispatch",
            "lifecycle routed by facade/local/aws-staging: "
            f"{str(facade_complete).lower()}/"
            f"{str(local_complete).lower()}/"
            f"{str(aws_complete).lower()}",
            {
                "facade_executable": facade_executable,
                "profiles_are_closed": True,
                "facade_lifecycle_complete": facade_complete,
                "local_lifecycle_complete": local_complete,
                "aws_lifecycle_complete": aws_complete,
                "common_lifecycle_complete": lifecycle_complete,
            },
        ),
        record(
            "local-first-use",
            _STRATEGY_PATHS["local"],
            "local first-use controls",
            f"local first-use: {str(local_first_use_complete).lower()}",
            {
                "local_installs_pinned_tools": local_installs_pinned_tools,
                "local_uses_checkout_state": local_uses_checkout_state,
                "local_uses_explicit_context": local_uses_explicit_context,
                "local_prints_next_command": local_prints_next_command,
                "local_first_use_complete": local_first_use_complete,
            },
        ),
        record(
            "aws-onboarding",
            _STRATEGY_PATHS["aws-staging"],
            "aws onboarding and teardown controls",
            f"aws onboarding: {str(aws_onboarding_complete).lower()}",
            {
                "aws_lifecycle_complete": aws_complete,
                "aws_setup_plans_by_default": aws_setup_plans_by_default,
                "aws_setup_reports_targets": aws_setup_reports_targets,
                "aws_secrets_from_stdin": aws_secrets_from_stdin,
                "aws_prints_next_command": aws_prints_next_command,
                "aws_teardown_operator_confirmed": aws_teardown_operator_confirmed,
                "aws_onboarding_complete": aws_onboarding_complete,
            },
        ),
    )
    return CollectorResult(
        evidence=evidence,
        coverage=CollectorCoverage(FLEET_LIFECYCLE_COLLECTOR_ID, "ok", len(evidence)),
    )
