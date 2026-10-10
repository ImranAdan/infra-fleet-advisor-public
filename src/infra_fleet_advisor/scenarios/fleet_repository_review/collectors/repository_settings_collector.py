"""Repository security-and-analysis settings, from a pre-fetched snapshot (PDR 0009).

The review stays offline: `infra-fleet-advisor settings-snapshot` reads the
settings from the GitHub API beforehand, and this collector only validates
that file. An unknown value or a malformed file leaves coverage partial, and
without a snapshot the collector does not run, so S-012 is never satisfied by
absence."""

import json
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_REPOSITORY_SECURITY_SETTINGS,
    REPOSITORY_SETTINGS_COLLECTOR_ID,
    REPOSITORY_SETTINGS_COLLECTOR_VERSION,
)

SNAPSHOT_SCHEMA = "repository-settings/v1"
SNAPSHOT_KEYS = frozenset(
    {"schema", "repository", "fetched_at", "dependabot_alerts", "security_updates", "reason"}
)
_MAX_SNAPSHOT_BYTES = 16 * 1024
# Settings have no file of their own; evidence anchors on the Dependabot
# configuration they complete, so published links stay valid.
_ANCHOR_PATH = ".github/dependabot.yml"


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _partial(reason: str) -> CollectorResult:
    return CollectorResult(
        (), CollectorCoverage(REPOSITORY_SETTINGS_COLLECTOR_ID, "partial", 0, reason)
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
    for key in ("dependabot_alerts", "security_updates"):
        if data[key] is not None and not isinstance(data[key], bool):
            raise ValueError(f"{key} is not a boolean or null")
    return data


def collect(snapshot_path: Path, repository_name: str) -> CollectorResult:
    try:
        data = _load(snapshot_path, repository_name)
    except (OSError, UnicodeError, ValueError) as error:
        return _partial(f"repository settings snapshot rejected: {type(error).__name__}")
    alerts, updates = data["dependabot_alerts"], data["security_updates"]
    if not isinstance(alerts, bool) or not isinstance(updates, bool):
        return _partial(f"repository settings unknown: {str(data['reason'])[:120]}")

    def word(value: bool) -> str:
        return "on" if value else "off"

    evidence = build_evidence(
        collector_id=REPOSITORY_SETTINGS_COLLECTOR_ID,
        collector_version=REPOSITORY_SETTINGS_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_REPOSITORY_SECURITY_SETTINGS,
        source_path=_ANCHOR_PATH,
        locator="settings:security-and-analysis",
        excerpt=(
            f"repository settings for {data['repository']} at {data['fetched_at']}: "
            f"Dependabot alerts {word(alerts)}, Dependabot security updates {word(updates)}"
        ),
        fact={
            "dependabot_alerts": alerts,
            "security_updates": updates,
            "enabled": alerts and updates,
        },
        identity_parts=("security-and-analysis", str(data["repository"])),
    )
    return CollectorResult(
        (evidence,), CollectorCoverage(REPOSITORY_SETTINGS_COLLECTOR_ID, "ok", 1, None)
    )
