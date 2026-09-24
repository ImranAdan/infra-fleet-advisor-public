"""The ratchet guard: an advisor change may add proof and findings, never lose them.

Two reviews of the same fleet commit are compared, one by the base advisor and
one by the proposed advisor. The fleet is held constant, so every difference is
the advisor's doing:

- a position that gains a decisive result (proof or a finding) moves the ratchet up;
- a position that loses its decisive result, or its check, lost proof;
- a divergence that becomes satisfied vanished without any fleet change, which
  means a check got weaker or a false positive was fixed, and either needs a
  stated justification from a maintainer.
"""

from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.runtime.intent_gate import Position, load_report, positions
from infra_fleet_advisor.runtime.report_writer import _safe_markdown_text

_UNVERIFIED = "declared_unverified"


@dataclass(frozen=True, slots=True)
class RatchetResult:
    new_proof: tuple[Position, ...]
    new_findings: tuple[Position, ...]
    lost_proof: tuple[Position, ...]
    lost_checks: tuple[Position, ...]
    vanished_findings: tuple[Position, ...]
    base_score: tuple[int, int, int]
    head_score: tuple[int, int, int]

    @property
    def passed(self) -> bool:
        return not (self.lost_proof or self.lost_checks or self.vanished_findings)


def _score(items: dict[str, Position]) -> tuple[int, int, int]:
    """(checked, satisfied, divergent)."""
    return (
        sum(p.check_key is not None for p in items.values()),
        sum(p.status == "satisfied" for p in items.values()),
        sum(p.status == "divergent" for p in items.values()),
    )


def compare_advisors(base_path: Path, head_path: Path) -> RatchetResult:
    before, after = positions(load_report(base_path)), positions(load_report(head_path))
    new_proof, new_findings, lost_proof, lost_checks, vanished = [], [], [], [], []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if new is None:
            # A position removed from the catalog takes its check with it.
            if old is not None and old.check_key is not None:
                lost_checks.append(old)
            continue
        was = old.status if old is not None else _UNVERIFIED
        if old is not None and old.check_key is not None and new.check_key is None:
            lost_checks.append(new)
        elif was != _UNVERIFIED and new.status == _UNVERIFIED:
            lost_proof.append(new)
        elif was == "divergent" and new.status == "satisfied":
            vanished.append(new)
        elif was != "satisfied" and new.status == "satisfied":
            new_proof.append(new)
        elif was != "divergent" and new.status == "divergent":
            new_findings.append(new)
    return RatchetResult(
        new_proof=tuple(new_proof),
        new_findings=tuple(new_findings),
        lost_proof=tuple(lost_proof),
        lost_checks=tuple(lost_checks),
        vanished_findings=tuple(vanished),
        base_score=_score(before),
        head_score=_score(after),
    )


def to_markdown(result: RatchetResult) -> str:
    (bc, bs, bd), (hc, hs, hd) = result.base_score, result.head_score
    verdict = "holds" if result.passed else "slipped"
    lines = [
        f"## Ratchet guard {verdict}",
        "",
        "The same fleet commit, reviewed by the base advisor and by this change:",
        "",
        "| | checked | satisfied | divergent |",
        "|---|---|---|---|",
        f"| base | {bc} | {bs} | {bd} |",
        f"| this change | {hc} | {hs} | {hd} |",
        "",
    ]

    def section(title: str, items: tuple[Position, ...]) -> None:
        if items:
            lines.extend([f"### {title}", ""])
            lines.extend(f"- `{p.key}` — {_safe_markdown_text(p.statement)}" for p in items)
            lines.append("")

    section("Lost proof (a decisive result became unverified)", result.lost_proof)
    section("Lost checks (a checked position no longer has one)", result.lost_checks)
    section(
        "Vanished findings (divergent became satisfied without a fleet change)",
        result.vanished_findings,
    )
    section("New proof", result.new_proof)
    section("New findings", result.new_findings)
    if not result.passed:
        lines.append(
            "A slip is sometimes right, for example fixing a false positive. Say why in the "
            "pull request; the guard makes the change visible, it does not forbid it."
        )
    return "\n".join(lines) + "\n"
