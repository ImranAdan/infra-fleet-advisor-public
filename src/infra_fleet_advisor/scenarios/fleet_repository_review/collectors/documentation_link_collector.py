"""Relative links in tracked Markdown resolve to tracked files or directories.

Evidence is one record per Markdown file, so a fleet with no broken link is
proven by complete coverage, not by silence. Links inside fenced code blocks,
absolute URLs, site-absolute paths and pure #anchors are not file links."""

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    DOCUMENTATION_LINK_COLLECTOR_ID,
    DOCUMENTATION_LINK_COLLECTOR_VERSION,
    EVIDENCE_KIND_DOCUMENTATION_LINKS,
)

_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_MAX_EVIDENCE = 200


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def broken_links(source: str, text: str, known: frozenset[str]) -> list[str]:
    """Relative link targets in `text` (from file `source`) missing from `known`."""
    missing = []
    for match in _LINK.finditer(_FENCE.sub("", text)):
        target = match.group(1).split("#", 1)[0].split("?", 1)[0]
        if not target or _SCHEME.match(target) or target.startswith("/"):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
        if resolved.startswith("..") or resolved not in known:
            missing.append(match.group(1))
    return missing


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str],
    tracked_paths: frozenset[str],
) -> CollectorResult:
    directories = {"."}
    for path in tracked_paths:
        parent = posixpath.dirname(path)
        while parent and parent not in directories:
            directories.add(parent)
            parent = posixpath.dirname(parent)
    known = frozenset(tracked_paths | directories)
    documents = sorted(
        path
        for path in tracked_paths
        if path.endswith(".md")
        and not any(path == ex or path.startswith(f"{ex}/") for ex in excluded_paths)
    )
    evidence: list[Evidence] = []
    failures = 0
    for path in documents[:_MAX_EVIDENCE]:
        file = checkout_root / path
        try:
            if file.is_symlink() or file.stat().st_size > limits.max_file_bytes:
                raise ValueError("symlink or oversized")
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            failures += 1
            continue
        missing = broken_links(path, text, known)
        evidence.append(
            build_evidence(
                collector_id=DOCUMENTATION_LINK_COLLECTOR_ID,
                collector_version=DOCUMENTATION_LINK_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_DOCUMENTATION_LINKS,
                source_path=path,
                locator="links",
                excerpt=(
                    f"{path}: {len(missing)} broken relative link(s): " + ", ".join(missing)
                    if missing
                    else f"{path}: every relative link resolves"
                ),
                fact={"links_resolve": not missing, "broken_links": len(missing)},
                identity_parts=(path,),
            )
        )
    reasons = []
    if failures:
        reasons.append(f"{failures} Markdown file(s) could not be read")
    if len(documents) > _MAX_EVIDENCE:
        reasons.append("Markdown files omitted by safety limit")
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(
            DOCUMENTATION_LINK_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(evidence),
            "; ".join(reasons) or None,
        ),
    )
