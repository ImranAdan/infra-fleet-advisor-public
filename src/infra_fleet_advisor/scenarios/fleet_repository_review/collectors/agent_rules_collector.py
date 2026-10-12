"""The fleet still declares the rules that let agents work end to end (M-006).

Whether an agent paused is not repository evidence, so this cannot prove the
position. It catches the regression that would make pausing the rule: losing
the autonomy grant or owner-only list from AGENTS.md, or the opt-in marker the
trusted merge worker looks for from the pull request template. One record per
file that exists; a missing file yields no record."""

from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    AGENT_RULES_COLLECTOR_ID,
    AGENT_RULES_COLLECTOR_VERSION,
    EVIDENCE_KIND_AGENT_AUTONOMY_RULES,
)

# File -> markers that must all be present.
RULES: dict[str, tuple[str, ...]] = {
    "AGENTS.md": ("## Autonomy", "**Owner-only actions.**"),
    ".github/pull_request_template.md": ("<!-- autonomous-merge -->",),
}


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str],
    tracked_paths: frozenset[str],
) -> CollectorResult:
    evidence: list[Evidence] = []
    failures = 0
    for path, markers in RULES.items():
        if path not in tracked_paths or any(
            path == ex or path.startswith(f"{ex}/") for ex in excluded_paths
        ):
            continue
        file = checkout_root / path
        try:
            if file.is_symlink() or file.stat().st_size > limits.max_file_bytes:
                raise ValueError("symlink or oversized")
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            failures += 1
            continue
        missing = [marker for marker in markers if marker not in text]
        evidence.append(
            build_evidence(
                collector_id=AGENT_RULES_COLLECTOR_ID,
                collector_version=AGENT_RULES_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_AGENT_AUTONOMY_RULES,
                source_path=path,
                locator="agent-rules",
                excerpt=(
                    f"{path}: missing " + ", ".join(missing)
                    if missing
                    else f"{path}: declares " + ", ".join(markers)
                ),
                fact={"rules_present": not missing, "missing_markers": len(missing)},
                identity_parts=(path,),
            )
        )
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(
            AGENT_RULES_COLLECTOR_ID,
            "partial" if failures else "ok",
            len(evidence),
            f"{failures} agent rule file(s) could not be read" if failures else None,
        ),
    )
