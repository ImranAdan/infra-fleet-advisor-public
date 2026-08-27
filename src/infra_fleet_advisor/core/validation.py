import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

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


def _field_violation(
    *,
    concern_key: str,
    category: str,
    priority: str,
    confidence: float,
    title: str,
    text_fields: Sequence[str],
    bounds: PolicyBounds,
    allowed_concern_keys: frozenset[str],
) -> str | None:
    """Shared closed-schema/publication checks for anything about to be
    published as a Recommendation — a freshly synthesized candidate or a
    prior-report entry being carried forward. Same rules either way: an
    untrusted prior report gets no less scrutiny than a fresh synthesis."""
    if not isinstance(concern_key, str) or concern_key not in allowed_concern_keys:
        return "unknown_concern_key"
    if not isinstance(category, str) or category not in bounds.enabled_categories:
        return "category_not_enabled"
    if not isinstance(priority, str) or priority not in PRIORITIES:
        return "invalid_priority"
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return "confidence_out_of_range"
    if not (0.0 <= confidence <= 1.0):
        return "confidence_out_of_range"
    if any(not isinstance(f, str) for f in text_fields):
        return "non_string_field"
    if len(title) > MAX_TITLE_LENGTH:
        return "title_too_long"
    if any(len(f) > MAX_TEXT_FIELD_LENGTH for f in text_fields[1:5]):
        return "text_field_too_long"
    if len(text_fields[-1]) > MAX_EXPLANATION_LENGTH:
        return "explanation_too_long"
    if any(p.search(f) for f in text_fields for p in _SECRET_PATTERNS):
        return "secret_pattern_detected"
    return None


class PriorRecommendationLike(Protocol):
    """Structural type for anything with a Recommendation-shaped field set —
    matches frozen dataclasses like `PriorRecommendation` without importing
    them here (avoiding a lifecycle<->validation import cycle)."""

    @property
    def concern_key(self) -> str: ...
    @property
    def category(self) -> str: ...
    @property
    def priority(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def summary(self) -> str: ...
    @property
    def evidence_ids(self) -> Sequence[str]: ...
    @property
    def impact(self) -> str: ...
    @property
    def suggested_change(self) -> str: ...
    @property
    def trade_offs(self) -> str: ...
    @property
    def confidence(self) -> float: ...
    @property
    def confidence_explanation(self) -> str: ...


def is_prior_recommendation_valid(
    prior: PriorRecommendationLike,
    bounds: PolicyBounds,
    allowed_concern_keys: frozenset[str],
) -> bool:
    """Gate for republishing a prior-report entry (as resolved/carried-forward).
    A prior report is untrusted input — it gets the same field checks as a
    fresh candidate, minus the evidence-resolution check (its evidence is
    expected to no longer be in the current evidence set; that's what makes
    it prior)."""
    if (
        not isinstance(prior.evidence_ids, (list, tuple))
        or not prior.evidence_ids
        or any(not isinstance(e, str) for e in prior.evidence_ids)
    ):
        return False
    if any(p.search(eid) for eid in prior.evidence_ids for p in _SECRET_PATTERNS):
        return False
    text_fields = (
        prior.title,
        prior.summary,
        prior.impact,
        prior.suggested_change,
        prior.trade_offs,
        prior.confidence_explanation,
    )
    reason = _field_violation(
        concern_key=prior.concern_key,
        category=prior.category,
        priority=prior.priority,
        confidence=prior.confidence,
        title=prior.title,
        text_fields=text_fields,
        bounds=bounds,
        allowed_concern_keys=allowed_concern_keys,
    )
    return reason is None


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
        elif (
            not isinstance(c.evidence_ids, (list, tuple))
            or not c.evidence_ids
            or any(not isinstance(e, str) for e in c.evidence_ids)
        ):
            # Type-checked before any hashing/lookup — an unhashable or
            # non-string evidence_id must reject this one candidate, never
            # crash the whole run.
            reason = "no_evidence_cited"
        elif any(eid not in evidence_by_id for eid in c.evidence_ids):
            reason = "invented_evidence_id"
        else:
            reason = _field_violation(
                concern_key=c.concern_key,
                category=c.category,
                priority=c.priority,
                confidence=c.confidence,
                title=c.title,
                text_fields=text_fields,
                bounds=bounds,
                allowed_concern_keys=allowed_concern_keys,
            )

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
                owner_accepted_trade_off=bounds.accepted_trade_offs.get(c.concern_key),
            )
        )

    return ValidatedRecommendations(accepted=tuple(accepted), rejected=tuple(rejected))
