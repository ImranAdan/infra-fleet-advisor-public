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


def assign_evidence_id(collector_id: str, *identity_parts: str) -> str:
    if not identity_parts:
        raise ValueError("evidence identity must have at least one part")
    digest = hashlib.sha256("|".join(identity_parts).encode()).hexdigest()[:16]
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
    identity_parts: tuple[str, ...] | None = None,
) -> Evidence:
    safe_path = validate_repo_relative_path(source_path)
    identity = identity_parts if identity_parts is not None else (safe_path, locator)
    return Evidence(
        evidence_id=assign_evidence_id(collector_id, *identity),
        kind=kind,
        source_path=safe_path,
        locator=locator,
        excerpt=excerpt[:MAX_EXCERPT_LENGTH],
        fact=dict(fact),
        collector_id=collector_id,
        collector_version=collector_version,
    )
