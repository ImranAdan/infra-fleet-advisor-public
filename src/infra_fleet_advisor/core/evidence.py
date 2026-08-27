import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from infra_fleet_advisor.core.paths import validate_repo_relative_path

MAX_EXCERPT_LENGTH = 280
FactValue = bool | str | int


@dataclass(frozen=True, slots=True)
class Evidence:
    """fact must hold only bounded, non-secret, JSON-primitive values."""

    evidence_id: str
    kind: str
    source_path: str
    locator: str
    excerpt: str
    fact: Mapping[str, FactValue] = field(default_factory=dict)
    collector_id: str = ""
    collector_version: str = ""


def assign_evidence_id(collector_id: str, source_path: str, locator: str) -> str:
    digest = hashlib.sha256(f"{source_path}|{locator}".encode()).hexdigest()[:16]
    return f"{collector_id}:{digest}"


def build_evidence(
    *,
    collector_id: str,
    collector_version: str,
    kind: str,
    source_path: str,
    locator: str,
    excerpt: str,
    fact: Mapping[str, FactValue],
) -> Evidence:
    safe_path = validate_repo_relative_path(source_path)
    return Evidence(
        evidence_id=assign_evidence_id(collector_id, safe_path, locator),
        kind=kind,
        source_path=safe_path,
        locator=locator,
        excerpt=excerpt[:MAX_EXCERPT_LENGTH],
        fact=dict(fact),
        collector_id=collector_id,
        collector_version=collector_version,
    )
