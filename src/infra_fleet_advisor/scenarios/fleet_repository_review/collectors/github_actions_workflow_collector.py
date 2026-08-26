from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    COLLECTOR_ID,
    COLLECTOR_VERSION,
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_TRIVY_GATE,
)

_CREDENTIALS_ACTION_PREFIX = "aws-actions/configure-aws-credentials"
_TRIVY_ACTION_PREFIX = "aquasecurity/trivy-action"


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


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


def collect(checkout_root: Path, limits: ExecutionLimits) -> CollectorResult:
    workflows_dir = checkout_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                collector_id=COLLECTOR_ID,
                status="failed",
                evidence_count=0,
                error_summary="no .github/workflows directory found",
            ),
        )

    files = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])[
        : limits.max_workflow_files
    ]

    evidence: list[Evidence] = []
    failures = 0
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
        try:
            if path.stat().st_size > limits.max_file_bytes:
                failures += 1
                continue
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(workflow, dict):
                failures += 1
                continue
        except (OSError, yaml.YAMLError):
            failures += 1
            continue

        for locator, step in _iter_steps(workflow, rel_path):
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            raw_with = step.get("with")
            with_block: dict[str, Any] = raw_with if isinstance(raw_with, dict) else {}

            if uses.startswith(_CREDENTIALS_ACTION_PREFIX):
                evidence.append(
                    build_evidence(
                        collector_id=COLLECTOR_ID,
                        collector_version=COLLECTOR_VERSION,
                        kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
                        source_path=rel_path,
                        locator=locator,
                        excerpt=f"uses: {uses}",
                        fact={
                            "uses_role_to_assume": "role-to-assume" in with_block,
                            "uses_static_keys": (
                                "aws-access-key-id" in with_block
                                or "aws-secret-access-key" in with_block
                            ),
                        },
                    )
                )
            elif uses.startswith(_TRIVY_ACTION_PREFIX):
                evidence.append(
                    build_evidence(
                        collector_id=COLLECTOR_ID,
                        collector_version=COLLECTOR_VERSION,
                        kind=EVIDENCE_KIND_TRIVY_GATE,
                        source_path=rel_path,
                        locator=locator,
                        excerpt=f"uses: {uses}",
                        fact={"ignore_unfixed": str(with_block.get("ignore-unfixed")) == "true"},
                    )
                )

    if not files:
        status = "failed"
    elif failures:
        status = "partial"
    else:
        status = "ok"

    return CollectorResult(
        evidence=tuple(evidence),
        coverage=CollectorCoverage(
            collector_id=COLLECTOR_ID,
            status=status,
            evidence_count=len(evidence),
            error_summary=f"{failures} unreadable/malformed workflow file(s)" if failures else None,
        ),
    )
