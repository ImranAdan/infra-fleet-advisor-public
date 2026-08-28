"""Mechanical patches for a narrow set of concerns.

A patch is only ever derived from a published recommendation and the evidence it
cites, never from scanning the fleet. That keeps remediation inside the same
evidence boundary as advice: nothing is edited that the report did not already
justify, and a finding that failed validation can never produce a patch.

Most concerns are not mechanically fixable and must not be. Scoping a wildcard
IAM policy needs to know which API calls a pipeline actually makes; guessing at
that would produce a confident, wrong, security-relevant change.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.paths import validate_repo_relative_path
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_TRIVY_IGNORE_UNFIXED,
)

# `ignore-unfixed: true` as its own YAML mapping entry. Anchored to the whole
# line so a value inside a longer expression is left alone.
_IGNORE_UNFIXED_LINE = re.compile(r"(?m)^[ \t]*ignore-unfixed[ \t]*:[ \t]*true[ \t]*\r?\n")


@dataclass(frozen=True, slots=True)
class Patch:
    """A single file edit proposed for one concern."""

    path: str
    original: str
    patched: str
    summary: str

    @property
    def changes_anything(self) -> bool:
        return self.original != self.patched


def _drop_ignore_unfixed(text: str) -> tuple[str, str]:
    patched, count = _IGNORE_UNFIXED_LINE.subn("", text)
    if count == 0:
        return text, "no ignore-unfixed entry found"
    return patched, f"removed {count} ignore-unfixed entry/entries"


# concern_key -> (text transform). Deliberately tiny. Adding an entry here is a
# claim that the change is safe without human judgement, which is rarely true.
PATCHERS: Mapping[str, Callable[[str], tuple[str, str]]] = {
    CONCERN_TRIVY_IGNORE_UNFIXED: _drop_ignore_unfixed,
}


def patchable_concerns() -> frozenset[str]:
    return frozenset(PATCHERS)


def build_patches(
    *,
    checkout_root: Path,
    concern_key: str,
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Evidence],
    max_file_bytes: int = 256 * 1024,
) -> tuple[Patch, ...]:
    """Produce the edits one recommendation implies. Files are located only via
    the evidence the recommendation cites, so an unreferenced file cannot be
    touched even if it contains the same pattern."""
    patcher = PATCHERS.get(concern_key)
    if patcher is None:
        return ()

    patches: list[Patch] = []
    seen: set[str] = set()
    for eid in evidence_ids:
        item = evidence_by_id.get(eid)
        if item is None or item.source_path in seen:
            continue
        seen.add(item.source_path)

        safe = validate_repo_relative_path(item.source_path)
        target = (checkout_root / safe).resolve()
        if not target.is_relative_to(checkout_root.resolve()):
            raise UnsafePathError(f"evidence path escapes the checkout: {safe!r}")
        if target.is_symlink() or not target.is_file():
            continue
        if target.stat().st_size > max_file_bytes:
            continue

        original = target.read_text(encoding="utf-8")
        patched, summary = patcher(original)
        patches.append(Patch(path=safe, original=original, patched=patched, summary=summary))

    return tuple(p for p in patches if p.changes_anything)


def apply_patches(checkout_root: Path, patches: Sequence[Patch]) -> tuple[str, ...]:
    """Write the patches. Returns the paths actually modified."""
    written: list[str] = []
    for patch in patches:
        target = checkout_root / validate_repo_relative_path(patch.path)
        target.write_text(patch.patched, encoding="utf-8")
        written.append(patch.path)
    return tuple(written)
