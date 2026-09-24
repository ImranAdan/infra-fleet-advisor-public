import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.paths import validate_repo_relative_path
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_ECR_PUBLICATION_GATE,
    EVIDENCE_KIND_TRIVY_GATE,
    GHA_COLLECTOR_ID,
    GHA_COLLECTOR_VERSION,
)

_CREDENTIALS_ACTION = "aws-actions/configure-aws-credentials"
_TRIVY_ACTION = "aquasecurity/trivy-action"
_LOCAL_ACTION = re.compile(r"^\./([A-Za-z0-9_.][A-Za-z0-9_./-]*)$")
_ECR_LOGIN_ACTION = "aws-actions/amazon-ecr-login"
_DOCKER_LOGIN_ACTION = "docker/login-action"
_ECR_LOGIN_COMMAND = re.compile(r"\becr\s+get-login-password\b")
_ECR_REGISTRY = re.compile(r"\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com")
_BUILD_PUSH_ACTION = "docker/build-push-action"
_PUSH_COMMAND = re.compile(
    r"\bdocker\s+(?:image\s+)?push\b|\bdocker\s+buildx\s+build\b[^\n]*--push\b"
)
# A job condition calling one of these still runs after its dependencies fail.
_STATUS_OVERRIDE = re.compile(r"\b(?:always|failure|cancelled)\s*\(")


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _matches_action(uses: str, action: str) -> bool:
    """`uses == action` (no ref) or `uses.startswith(f"{action}@")` — a bare
    prefix match would also accept an unrelated action like
    `aws-actions/configure-aws-credentials-role-chaining@v1`."""
    return uses == action or uses.startswith(f"{action}@")


def _is_truthy_yaml_value(value: Any) -> bool:
    """GitHub Actions `with:` values are commonly unquoted YAML booleans
    (parsed as Python `True`) or quoted strings (`"true"`) — both must count."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _grants_id_token_write(permissions: Any) -> bool:
    if isinstance(permissions, str):
        return permissions.strip().lower() == "write-all"
    if not isinstance(permissions, dict):
        return False
    value = permissions.get("id-token")
    return isinstance(value, str) and value.strip().lower() == "write"


def _input_is_disabled(with_block: dict[str, Any], key: str) -> bool:
    if key not in with_block:
        return True
    value = with_block[key]
    if isinstance(value, bool):
        return not value
    return isinstance(value, str) and value.strip().lower() == "false"


def _iter_steps(workflow: dict[str, Any], rel_path: str) -> list[tuple[str, dict[str, Any], bool]]:
    steps: list[tuple[str, dict[str, Any], bool]] = []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return steps
    workflow_permissions = workflow.get("permissions")
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        effective_permissions = (
            job.get("permissions") if "permissions" in job else workflow_permissions
        )
        has_id_token_write = _grants_id_token_write(effective_permissions)
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict):
                continue
            locator = f"jobs.{job_id}.steps[{step.get('id', index)}]"
            steps.append((f"{rel_path}::{locator}", step, has_id_token_write))
    return steps


def _build_step_evidence(
    rel_path: str,
    locator: str,
    step: dict[str, Any],
    has_id_token_write: bool,
) -> Evidence | None:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return None
    raw_with = step.get("with")
    with_block: dict[str, Any] = raw_with if isinstance(raw_with, dict) else {}

    if _matches_action(uses, _CREDENTIALS_ACTION):
        role_to_assume = with_block.get("role-to-assume")
        uses_role_to_assume = isinstance(role_to_assume, str) and bool(role_to_assume.strip())
        uses_static_keys = (
            "aws-access-key-id" in with_block or "aws-secret-access-key" in with_block
        )
        force_skip_oidc_disabled = _input_is_disabled(with_block, "force-skip-oidc")
        use_existing_credentials_disabled = _input_is_disabled(
            with_block, "use-existing-credentials"
        )
        return build_evidence(
            collector_id=GHA_COLLECTOR_ID,
            collector_version=GHA_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
            source_path=rel_path,
            locator=locator,
            excerpt=f"uses: {uses}",
            fact={
                "uses_role_to_assume": uses_role_to_assume,
                "uses_static_keys": uses_static_keys,
                "has_id_token_write": has_id_token_write,
                "force_skip_oidc_disabled": force_skip_oidc_disabled,
                "use_existing_credentials_disabled": use_existing_credentials_disabled,
                "uses_oidc_only": (
                    uses_role_to_assume
                    and not uses_static_keys
                    and has_id_token_write
                    and force_skip_oidc_disabled
                    and use_existing_credentials_disabled
                ),
            },
            # Workflow paths and step positions are still the best available
            # address for steps without an explicit id. Keep both identity
            # parts until GitHub Actions has a stable resource handle.
            identity_parts=(rel_path, locator),
        )
    if _matches_action(uses, _TRIVY_ACTION):
        return build_evidence(
            collector_id=GHA_COLLECTOR_ID,
            collector_version=GHA_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_TRIVY_GATE,
            source_path=rel_path,
            locator=locator,
            excerpt=f"uses: {uses}",
            fact={"ignore_unfixed": _is_truthy_yaml_value(with_block.get("ignore-unfixed"))},
            identity_parts=(rel_path, locator),
        )
    return None


def _is_blocking_scan(step: dict[str, Any]) -> bool:
    """A Trivy step that fails its job on any Critical or High finding."""
    uses = step.get("uses")
    if not isinstance(uses, str) or not _matches_action(uses, _TRIVY_ACTION):
        return False
    raw_with = step.get("with")
    with_block: dict[str, Any] = raw_with if isinstance(raw_with, dict) else {}
    severity = with_block.get("severity")
    severities = (
        {"CRITICAL", "HIGH"}
        if severity is None
        else {part.strip().upper() for part in str(severity).split(",")}
    )
    exit_code = str(with_block.get("exit-code", "0")).strip()
    scanners = with_block.get("scanners")
    return (
        # Only an image vulnerability scan says anything about what is published.
        str(with_block.get("scan-type", "image")).strip() == "image"
        and isinstance(with_block.get("image-ref"), str)
        and (scanners is None or "vuln" in str(scanners).split(","))
        and {"CRITICAL", "HIGH"} <= severities
        and exit_code.isdigit()
        and int(exit_code) != 0
        and "if" not in step
        and not _is_truthy_yaml_value(step.get("continue-on-error"))
    )


def _pushes_image(step: dict[str, Any]) -> bool:
    uses = step.get("uses")
    if isinstance(uses, str):
        raw_with = step.get("with")
        return (
            _matches_action(uses, _BUILD_PUSH_ACTION)
            and isinstance(raw_with, dict)
            and _is_truthy_yaml_value(raw_with.get("push"))
        )
    run = step.get("run")
    return isinstance(run, str) and _PUSH_COMMAND.search(run) is not None


def _overrides_status(step_or_job: dict[str, Any]) -> bool:
    condition = step_or_job.get("if")
    return isinstance(condition, str) and _STATUS_OVERRIDE.search(condition) is not None


def _logs_in_to_ecr(step: dict[str, Any]) -> bool:
    uses = step.get("uses")
    if isinstance(uses, str):
        if _matches_action(uses, _ECR_LOGIN_ACTION):
            return True
        raw_with = step.get("with")
        registry = raw_with.get("registry") if isinstance(raw_with, dict) else None
        return (
            _matches_action(uses, _DOCKER_LOGIN_ACTION)
            and isinstance(registry, str)
            and _ECR_REGISTRY.search(registry) is not None
        )
    run = step.get("run")
    return isinstance(run, str) and _ECR_LOGIN_COMMAND.search(run) is not None


def _publication_evidence(workflow: dict[str, Any], rel_path: str) -> list[Evidence]:
    """One record per job that pushes to ECR: is it gated by a blocking scan?

    A job is gated when a blocking scan runs earlier in the same job, or in a
    job it reaches through `needs` without any job on that path overriding
    dependency failure with always(), failure() or cancelled()."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    steps_by_job = {
        job_id: [step for step in (job.get("steps") or []) if isinstance(step, dict)]
        for job_id, job in jobs.items()
        if isinstance(job, dict)
    }

    def needs(job_id: str) -> list[str]:
        value = jobs[job_id].get("needs")
        if isinstance(value, str):
            return [value]
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    # GitHub rejects cyclic needs, so a job's answer is path-independent; memoise
    # it to keep dense fan-in graphs linear instead of enumerating every path.
    gated_memo: dict[str, bool] = {}

    def gated_by_dependency(job_id: str) -> bool:
        if job_id not in gated_memo:
            gated_memo[job_id] = False  # guards malformed cycles while computing
            gated_memo[job_id] = not _overrides_status(jobs[job_id]) and any(
                any(_is_blocking_scan(step) for step in steps_by_job[dependency])
                or gated_by_dependency(dependency)
                for dependency in needs(job_id)
                if dependency in steps_by_job
            )
        return gated_memo[job_id]

    evidence = []
    for job_id, steps in steps_by_job.items():
        # Publication is an ECR login followed by an image push; a login alone
        # may only pull a private base image.
        login_at = next((i for i, step in enumerate(steps) if _logs_in_to_ecr(step)), None)
        if login_at is None or not any(_pushes_image(step) for step in steps[login_at:]):
            continue
        publication_path = [
            step for step in steps[login_at:] if _logs_in_to_ecr(step) or _pushes_image(step)
        ]
        scanned_first = any(_is_blocking_scan(step) for step in steps[:login_at]) and not any(
            _overrides_status(step) for step in publication_path
        )
        gated = scanned_first or gated_by_dependency(job_id)
        locator = f"jobs.{job_id}"
        evidence.append(
            build_evidence(
                collector_id=GHA_COLLECTOR_ID,
                collector_version=GHA_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_ECR_PUBLICATION_GATE,
                source_path=rel_path,
                locator=locator,
                excerpt=(
                    f"{locator} pushes to ECR; blocking Critical/High scan before it: "
                    f"{str(gated).lower()}"
                ),
                fact={"gated_by_blocking_scan": gated},
                identity_parts=(rel_path, locator),
            )
        )
    return evidence


def _local_action_steps(
    checkout_root: Path,
    uses: str,
    limits: ExecutionLimits,
    tracked_paths: frozenset[str] | None,
    excluded_paths: frozenset[str] = frozenset(),
) -> tuple[str, list[dict[str, Any]]] | None:
    """Steps of a tracked local composite action a workflow step calls.

    Credentials obtained inside a `./` action are as real as ones in the
    workflow. Returns None for a non-local `uses:`; raises ValueError when a
    local action cannot be read from the verified commit, or when it calls a
    further local action, which is not followed and so leaves coverage partial.
    ponytail: one level only; add recursion with a visited set if the fleet
    grows nested local actions."""
    match = _LOCAL_ACTION.fullmatch(uses)
    if match is None:
        return None
    directory = match.group(1).rstrip("/")
    checkout_real = checkout_root.resolve()
    for name in ("action.yml", "action.yaml"):
        rel_path = validate_repo_relative_path(f"{directory}/{name}")
        path = checkout_root / rel_path
        if not path.is_file():
            continue
        if _is_excluded(rel_path, excluded_paths):
            return rel_path, []  # excluded content is never evidence
        if tracked_paths is not None and rel_path not in tracked_paths:
            raise ValueError("local action is not part of the verified commit")
        if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
            raise ValueError("local action is not a regular in-checkout file")
        if path.stat().st_size > limits.max_file_bytes:
            raise ValueError("local action exceeds max_file_bytes")
        action = yaml.safe_load(path.read_text(encoding="utf-8"))
        runs = action.get("runs") if isinstance(action, dict) else None
        if not isinstance(runs, dict) or runs.get("using") != "composite":
            return rel_path, []
        steps = runs.get("steps")
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise ValueError("local composite action steps are malformed")
        if any(
            isinstance(step.get("uses"), str) and _LOCAL_ACTION.fullmatch(step["uses"])
            for step in steps
        ):
            raise ValueError("nested local action is not followed")
        return rel_path, steps
    raise ValueError("local action has no action.yml")


def _is_excluded(rel_path: str, excluded_paths: frozenset[str]) -> bool:
    return any(
        rel_path == excluded or rel_path.startswith(f"{excluded}/") for excluded in excluded_paths
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    checkout_real = checkout_root.resolve()
    workflows_dir = checkout_root / ".github" / "workflows"
    if not workflows_dir.is_dir() or not workflows_dir.resolve().is_relative_to(checkout_real):
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                collector_id=GHA_COLLECTOR_ID,
                status="failed",
                evidence_count=0,
                error_summary="no .github/workflows directory found",
            ),
        )

    all_files = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])
    eligible_files: list[Path] = []
    excluded_count = 0
    untracked_count = 0
    for path in all_files:
        rel_path = path.relative_to(checkout_root).as_posix()
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
        elif tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
        else:
            eligible_files.append(path)
    files = eligible_files[: limits.max_workflow_files]
    truncated_count = len(eligible_files) - len(files)

    evidence: list[Evidence] = []
    failures = 0
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
        try:
            if path.is_symlink():
                # A tracked link does not make its ignored target source evidence.
                failures += 1
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(checkout_real):
                # A symlink escaping the verified checkout — never read
                # content that wasn't part of the verified snapshot.
                failures += 1
                continue
            if path.stat().st_size > limits.max_file_bytes:
                failures += 1
                continue
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(workflow, dict):
                failures += 1
                continue
            for locator, step, has_id_token_write in _iter_steps(workflow, rel_path):
                item = _build_step_evidence(rel_path, locator, step, has_id_token_write)
                if item is not None:
                    evidence.append(item)
                uses = step.get("uses")
                try:
                    local = (
                        _local_action_steps(
                            checkout_root, uses, limits, tracked_paths, excluded_paths
                        )
                        if isinstance(uses, str)
                        else None
                    )
                except ValueError:
                    failures += 1
                    continue
                if local is None:
                    continue
                action_path, action_steps = local
                for index, action_step in enumerate(action_steps):
                    # The composite runs with the calling job's permissions, and
                    # each caller is its own credential path.
                    item = _build_step_evidence(
                        action_path, f"{locator} -> steps[{index}]", action_step, has_id_token_write
                    )
                    if item is not None:
                        evidence.append(item)
            evidence.extend(_publication_evidence(workflow, rel_path))
        except (OSError, yaml.YAMLError, UnsafePathError):
            failures += 1
            continue

    if not all_files:
        status = "failed"
    elif failures or truncated_count or untracked_count:
        status = "partial"
    else:
        status = "ok"

    summary_parts = []
    if failures:
        summary_parts.append(f"{failures} unreadable/malformed workflow file(s)")
    if truncated_count:
        summary_parts.append(f"{truncated_count} workflow file(s) omitted past max_workflow_files")
    if excluded_count:
        summary_parts.append(f"{excluded_count} workflow file(s) excluded by policy")
    if untracked_count:
        summary_parts.append(f"{untracked_count} workflow file(s) not part of the verified commit")

    return CollectorResult(
        evidence=tuple(evidence),
        coverage=CollectorCoverage(
            collector_id=GHA_COLLECTOR_ID,
            status=status,
            evidence_count=len(evidence),
            error_summary="; ".join(summary_parts) if summary_parts else None,
        ),
    )
