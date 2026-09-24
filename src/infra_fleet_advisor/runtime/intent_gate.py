"""Compare two reports of the same catalog: what would a fleet change do to intent?

The gate runs the ordinary review against a pull request's base and head and
diffs the per-position outcomes. It reads only the two reports it is given and
writes only a Markdown summary; the verdict is the process exit code.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.report_writer import _safe_markdown_text

_MAX_REPORT_BYTES = 4 * 1024 * 1024
_MAX_EVIDENCE_LINES = 5


@dataclass(frozen=True, slots=True)
class Position:
    key: str
    status: str
    statement: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GateResult:
    regressions: tuple[Position, ...]
    resolutions: tuple[Position, ...]
    persisting: tuple[Position, ...]
    degraded_collectors: tuple[str, ...]
    base_checked: int
    head_checked: int
    total: int

    @property
    def passed(self) -> bool:
        return not self.regressions


def _load(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_REPORT_BYTES:
            raise PolicyError("report exceeds the gate size limit")
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError("report could not be read") from exc
    if not isinstance(report, dict):
        raise PolicyError("report is not a JSON object")
    return report


def _positions(report: dict[str, Any]) -> dict[str, Position]:
    evidence = {
        item.get("evidence_id"): item
        for item in report.get("evidence", [])
        if isinstance(item, dict)
    }
    positions: dict[str, Position] = {}
    for item in report.get("intent_evaluations", []):
        if not isinstance(item, dict):
            raise PolicyError("intent evaluation is malformed")
        key = f"{item.get('document_id')}/{item.get('proposition_id')}"
        cited = [evidence.get(eid) for eid in item.get("evidence_ids", [])]
        positions[key] = Position(
            key=key,
            status=str(item.get("status")),
            statement=str(item.get("statement", "")).split("\n", 1)[0],
            evidence=tuple(
                f"{entry.get('source_path')} — {entry.get('excerpt')}"
                for entry in cited
                if isinstance(entry, dict)
            ),
        )
    return positions


def compare_reports(base_path: Path, head_path: Path) -> GateResult:
    base, head = _load(base_path), _load(head_path)
    base_digest = base.get("provenance", {}).get("intent_digest")
    if not base_digest or base_digest != head.get("provenance", {}).get("intent_digest"):
        raise PolicyError("base and head reports must evaluate the same intent catalog")
    before, after = _positions(base), _positions(head)
    regressions: list[Position] = []
    resolutions: list[Position] = []
    persisting: list[Position] = []
    for key, position in sorted(after.items()):
        was_divergent = before.get(key) is not None and before[key].status == "divergent"
        if position.status == "divergent":
            (persisting if was_divergent else regressions).append(position)
        elif was_divergent:
            resolutions.append(position)
    base_ok = {
        item.get("collector_id")
        for item in base.get("coverage", [])
        if isinstance(item, dict) and item.get("status") == "ok"
    }
    degraded = tuple(
        sorted(
            str(item.get("collector_id"))
            for item in head.get("coverage", [])
            if isinstance(item, dict)
            and item.get("collector_id") in base_ok
            and item.get("status") != "ok"
        )
    )

    def checked(positions: dict[str, Position]) -> int:
        return sum(p.status != "declared_unverified" for p in positions.values())

    return GateResult(
        regressions=tuple(regressions),
        resolutions=tuple(resolutions),
        persisting=tuple(persisting),
        degraded_collectors=degraded,
        base_checked=checked(before),
        head_checked=checked(after),
        total=len(after),
    )


def to_markdown(result: GateResult) -> str:
    verdict = (
        "passes: no declared position newly diverges"
        if result.passed
        else f"fails: {len(result.regressions)} declared position(s) would newly diverge"
    )
    lines = [f"## Intent gate {verdict}", ""]

    def section(title: str, positions: tuple[Position, ...], with_evidence: bool) -> None:
        if not positions:
            return
        lines.extend([f"### {title}", ""])
        for position in positions:
            lines.append(f"- `{position.key}` — {_safe_markdown_text(position.statement)}")
            if with_evidence:
                lines.extend(
                    f"  - {_safe_markdown_text(entry)}"
                    for entry in position.evidence[:_MAX_EVIDENCE_LINES]
                )
        lines.append("")

    section("Newly divergent", result.regressions, with_evidence=True)
    section("Resolved by this change", result.resolutions, with_evidence=False)
    section("Already divergent on the base", result.persisting, with_evidence=False)
    if result.degraded_collectors:
        lines.extend(
            [
                "### Coverage lost",
                "",
                *(f"- `{name}` was complete on the base" for name in result.degraded_collectors),
                "",
            ]
        )
    lines.append(
        f"Positions with a decisive result: {result.base_checked} on the base, "
        f"{result.head_checked} on the head, of {result.total}. Desired state only; "
        "nothing was applied."
    )
    return "\n".join(lines) + "\n"
