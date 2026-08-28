from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_TRIVY_GATE,
    GHA_COLLECTOR_ID,
    GHA_COLLECTOR_VERSION,
)

_CREDENTIALS_ACTION = "aws-actions/configure-aws-credentials"
_TRIVY_ACTION = "aquasecurity/trivy-action"


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


def _iter_steps(workflow: dict[str, Any], rel_path: str) -> list[tuple[str, dict[str, Any]]]:
    steps: list[tuple[str, dict[str, Any]]] = []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return steps
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict):
                continue
            locator = f"jobs.{job_id}.steps[{step.get('id', index)}]"
            steps.append((f"{rel_path}::{locator}", step))
    return steps


def _build_step_evidence(rel_path: str, locator: str, step: dict[str, Any]) -> Evidence | None:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return None
    raw_with = step.get("with")
    with_block: dict[str, Any] = raw_with if isinstance(raw_with, dict) else {}

    if _matches_action(uses, _CREDENTIALS_ACTION):
        return build_evidence(
            collector_id=GHA_COLLECTOR_ID,
            collector_version=GHA_COLLECTOR_VERSION,
            kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
            source_path=rel_path,
            locator=locator,
            excerpt=f"uses: {uses}",
            fact={
                "uses_role_to_assume": "role-to-assume" in with_block,
                "uses_static_keys": (
                    "aws-access-key-id" in with_block or "aws-secret-access-key" in with_block
                ),
            },
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
        )
    return None


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
    files = all_files[: limits.max_workflow_files]
    truncated_count = len(all_files) - len(files)

    evidence: list[Evidence] = []
    failures = 0
    excluded_count = 0
    untracked_count = 0
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
            continue
        if tracked_paths is not None and rel_path not in tracked_paths:
            # On disk but not part of the verified commit (e.g. .gitignore'd)
            # — git status doesn't flag ignored files as dirty, so this must
            # be checked explicitly rather than trusting the filesystem glob.
            untracked_count += 1
            continue
        try:
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
            for locator, step in _iter_steps(workflow, rel_path):
                item = _build_step_evidence(rel_path, locator, step)
                if item is not None:
                    evidence.append(item)
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
