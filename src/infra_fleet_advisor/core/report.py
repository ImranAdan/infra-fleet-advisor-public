from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import (
    PolicyBounds,
    RawRecommendationCandidate,
    Recommendation,
)
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.lifecycle import PriorReport, compare_with_prior
from infra_fleet_advisor.core.ranking import rank
from infra_fleet_advisor.core.validation import RejectedCandidate, validate_candidates


@dataclass(frozen=True, slots=True)
class CollectorCoverage:
    collector_id: str
    status: str  # "ok" | "partial" | "failed"
    evidence_count: int
    error_summary: str | None = None


@dataclass(frozen=True, slots=True)
class RunProvenance:
    source_commit_sha: str
    source_label: str
    advisor_version: str
    policy_version: str
    collector_versions: Mapping[str, str]
    model_identifier: str
    run_started_at: str


@dataclass(frozen=True, slots=True)
class Report:
    provenance: RunProvenance
    coverage: tuple[CollectorCoverage, ...]
    recommendations: tuple[Recommendation, ...]
    rejected_count: int
    new_count: int
    unchanged_count: int
    resolved_count: int
    suppressed_count: int


def assemble_report(
    *,
    provenance: RunProvenance,
    coverage: Sequence[CollectorCoverage],
    candidates: Sequence[RawRecommendationCandidate],
    evidence_by_id: Mapping[str, Evidence],
    bounds: PolicyBounds,
    allowed_concern_keys: frozenset[str],
    prior: PriorReport | None,
) -> tuple[Report, tuple[RejectedCandidate, ...]]:
    """Bounded pipeline coordination: validate → compare with prior → rank."""
    validated = validate_candidates(candidates, evidence_by_id, bounds, allowed_concern_keys)
    lifecycle = compare_with_prior(validated.accepted, prior, bounds.suppressed_concerns)
    ranked = rank(lifecycle.recommendations, bounds.category_priority)

    report = Report(
        provenance=provenance,
        coverage=tuple(coverage),
        recommendations=ranked,
        rejected_count=len(validated.rejected),
        new_count=lifecycle.new_count,
        unchanged_count=lifecycle.unchanged_count,
        resolved_count=lifecycle.resolved_count,
        suppressed_count=lifecycle.suppressed_count,
    )
    return report, validated.rejected
