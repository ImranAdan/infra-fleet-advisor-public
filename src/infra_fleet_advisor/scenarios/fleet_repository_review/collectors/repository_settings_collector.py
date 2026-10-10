"""Repository security settings, from a pre-fetched snapshot (PDR 0009).

The review stays offline: `infra-fleet-advisor settings-snapshot` reads the
settings from the GitHub API beforehand, and this collector only validates
that file. An unknown value or a malformed file leaves coverage partial, and
without a snapshot the collector does not run, so no settings position is
ever satisfied by absence."""

import json
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_DEFAULT_BRANCH_PROTECTION,
    EVIDENCE_KIND_REPOSITORY_SECRET_PROTECTION,
    EVIDENCE_KIND_REPOSITORY_SECURITY_SETTINGS,
    REPOSITORY_SETTINGS_COLLECTOR_ID,
    REPOSITORY_SETTINGS_COLLECTOR_VERSION,
)

SNAPSHOT_SCHEMA = "repository-settings/v2"
SETTING_KEYS = (
    "dependabot_alerts",
    "security_updates",
    "secret_scanning",
    "push_protection",
    "default_branch_protected",
)
SNAPSHOT_KEYS = frozenset({"schema", "repository", "fetched_at", "reason", *SETTING_KEYS})
_MAX_SNAPSHOT_BYTES = 16 * 1024

# (evidence kind, settings it joins, anchor file, what the excerpt names).
# Settings have no file of their own; each record anchors on the fleet file
# that documents the control, so published links stay valid.
_RECORDS = (
    (
        EVIDENCE_KIND_REPOSITORY_SECURITY_SETTINGS,
        ("dependabot_alerts", "security_updates"),
        ".github/dependabot.yml",
        ("Dependabot alerts", "Dependabot security updates"),
    ),
    (
        EVIDENCE_KIND_REPOSITORY_SECRET_PROTECTION,
        ("secret_scanning", "push_protection"),
        "SECURITY.md",
        ("secret scanning", "secret push protection"),
    ),
    (
        EVIDENCE_KIND_DEFAULT_BRANCH_PROTECTION,
        ("default_branch_protected",),
        "AGENTS.md",
        ("default-branch protection (pull requests required, no force-push or deletion)",),
    ),
)


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _partial(reason: str, evidence: tuple[Evidence, ...] = ()) -> CollectorResult:
    return CollectorResult(
        evidence,
        CollectorCoverage(REPOSITORY_SETTINGS_COLLECTOR_ID, "partial", len(evidence), reason),
    )


def _load(snapshot_path: Path, repository_name: str) -> dict[str, object]:
    if snapshot_path.is_symlink() or snapshot_path.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot is a symlink or too large")
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != SNAPSHOT_KEYS:
        raise ValueError("snapshot fields do not match the schema")
    if data["schema"] != SNAPSHOT_SCHEMA:
        raise ValueError("unknown snapshot schema")
    repository = data["repository"]
    if not isinstance(repository, str) or repository.rsplit("/", 1)[-1] != repository_name:
        raise ValueError("snapshot is for another repository")
    if not isinstance(data["fetched_at"], str) or not isinstance(data["reason"], str):
        raise ValueError("snapshot metadata is malformed")
    for key in SETTING_KEYS:
        if data[key] is not None and not isinstance(data[key], bool):
            raise ValueError(f"{key} is not a boolean or null")
    return data


def collect(snapshot_path: Path, repository_name: str) -> CollectorResult:
    try:
        data = _load(snapshot_path, repository_name)
    except (OSError, UnicodeError, ValueError) as error:
        return _partial(f"repository settings snapshot rejected: {type(error).__name__}")

    evidence: list[Evidence] = []
    unknown: list[str] = []
    for kind, keys, anchor, names in _RECORDS:
        raw = [data[key] for key in keys]
        if not all(isinstance(value, bool) for value in raw):
            unknown.extend(key for key, value in zip(keys, raw, strict=True) if value is None)
            continue
        values = [value is True for value in raw]
        states = ", ".join(
            f"{name} {'on' if value else 'off'}" for name, value in zip(names, values, strict=True)
        )
        evidence.append(
            build_evidence(
                collector_id=REPOSITORY_SETTINGS_COLLECTOR_ID,
                collector_version=REPOSITORY_SETTINGS_COLLECTOR_VERSION,
                kind=kind,
                source_path=anchor,
                locator=f"settings:{kind}",
                excerpt=(
                    f"repository settings for {data['repository']} at {data['fetched_at']}: "
                    + states
                ),
                fact={**dict(zip(keys, values, strict=True)), "enabled": all(values)},
                identity_parts=(kind, str(data["repository"])),
            )
        )
    if unknown:
        reason = str(data["reason"])[:120] or "no reason recorded"
        return _partial(
            f"repository settings unknown ({', '.join(unknown)}): {reason}", tuple(evidence)
        )
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(REPOSITORY_SETTINGS_COLLECTOR_ID, "ok", len(evidence), None),
    )
