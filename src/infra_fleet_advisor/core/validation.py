import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infra_fleet_advisor.core.contracts import (
    PRIORITIES,
    PolicyBounds,
    RawRecommendationCandidate,
    Recommendation,
    compute_fingerprint,
)
from infra_fleet_advisor.core.evidence import Evidence

MAX_TITLE_LENGTH = 120
MAX_TEXT_FIELD_LENGTH = 2000
MAX_EXPLANATION_LENGTH = 500

_SECRET_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"ghp_[A-Za-z0-9]{36}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
    )
)


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    """Records why a candidate was rejected — never its raw text."""

    concern_key: str
    category: str
    reason: str


@dataclass(frozen=True, slots=True)
class ValidatedRecommendations:
    accepted: tuple[Recommendation, ...]
    rejected: tuple[RejectedCandidate, ...]


def _reject(candidate: RawRecommendationCandidate, reason: str) -> RejectedCandidate:
    key = candidate.concern_key if isinstance(candidate.concern_key, str) else "unknown"
    cat = candidate.category if isinstance(candidate.category, str) else "unknown"
    return RejectedCandidate(concern_key=key[:80], category=cat[:80], reason=reason)


def validate_candidates(
    candidates: Sequence[RawRecommendationCandidate],
    evidence_by_id: Mapping[str, Evidence],
    bounds: PolicyBounds,
    allowed_concern_keys: frozenset[str],
) -> ValidatedRecommendations:
    """The sole publication gate. Text fields are only measured and
    pattern-matched, never interpolated into control flow — injected
    instructions inside them stay inert."""
    accepted: list[Recommendation] = []
    rejected: list[RejectedCandidate] = []

    for c in candidates:
        text_fields = (
            c.title,
            c.summary,
            c.impact,
            c.suggested_change,
            c.trade_offs,
            c.confidence_explanation,
        )
        reason = None
        if len(accepted) >= bounds.max_recommendations:
            reason = "max_recommendations_reached"
        elif c.concern_key not in allowed_concern_keys:
            reason = "unknown_concern_key"
        elif c.category not in bounds.enabled_categories:
            reason = "category_not_enabled"
        elif c.priority not in PRIORITIES:
            reason = "invalid_priority"
        elif not (0.0 <= c.confidence <= 1.0):
            reason = "confidence_out_of_range"
        elif not c.evidence_ids:
            reason = "no_evidence_cited"
        elif any(eid not in evidence_by_id for eid in c.evidence_ids):
            reason = "invented_evidence_id"
        elif any(not isinstance(f, str) for f in text_fields):
            reason = "non_string_field"
        elif len(c.title) > MAX_TITLE_LENGTH:
            reason = "title_too_long"
        elif any(len(f) > MAX_TEXT_FIELD_LENGTH for f in text_fields[1:5]):
            reason = "text_field_too_long"
        elif len(c.confidence_explanation) > MAX_EXPLANATION_LENGTH:
            reason = "explanation_too_long"
        elif any(p.search(f) for f in text_fields for p in _SECRET_PATTERNS):
            reason = "secret_pattern_detected"

        if reason:
            rejected.append(_reject(c, reason))
            continue

        accepted.append(
            Recommendation(
                fingerprint=compute_fingerprint(c.category, c.concern_key, c.evidence_ids),
                concern_key=c.concern_key,
                category=c.category,
                priority=c.priority,
                title=c.title,
                summary=c.summary,
                evidence_ids=tuple(c.evidence_ids),
                impact=c.impact,
                suggested_change=c.suggested_change,
                trade_offs=c.trade_offs,
                confidence=c.confidence,
                confidence_explanation=c.confidence_explanation,
                status="new",
            )
        )

    return ValidatedRecommendations(accepted=tuple(accepted), rejected=tuple(rejected))
