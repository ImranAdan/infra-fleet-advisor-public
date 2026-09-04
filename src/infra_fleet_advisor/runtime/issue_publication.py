import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.contracts import compute_fingerprint
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.validation import contains_secret, is_prior_recommendation_valid
from infra_fleet_advisor.runtime.report_writer import (
    load_prior_report,
    read_report_metadata,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import CONCERN_RULES
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY

FLEET_REPOSITORY = "ImranAdan/infra-fleet-public"
FLEET_SOURCE_LABEL = "infra-fleet-public"
MAX_ISSUE_ACTIONS = 100
MAX_ISSUE_BODY_CHARS = 60_000
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT = re.compile(r"^fp_[0-9a-f]{24}$")


@dataclass(frozen=True, slots=True)
class IssueAction:
    action: Literal["active", "resolved"]
    fingerprint: str
    concern_key: str
    fingerprint_label: str
    fingerprint_marker: str
    title: str
    body: str
    resolution_marker: str
    resolution_comment: str


@dataclass(frozen=True, slots=True)
class IssuePlan:
    target_repository: str
    source_commit_sha: str
    actions: tuple[IssueAction, ...]


def _safe_text(value: str) -> str:
    """Keep untrusted report text inert in GitHub-flavored Markdown."""
    collapsed = " ".join(value.split())
    escaped = html.escape(collapsed, quote=False)
    escaped = escaped.replace("\\", "\\\\")
    for character in "`*_{}[]#":
        escaped = escaped.replace(character, f"\\{character}")
    escaped = escaped.replace("@", "&#64;")
    escaped = re.sub(r"(?i)\b(https?)://", lambda match: f"{match.group(1)}&#58;//", escaped)
    escaped = re.sub(r"(?i)\bwww\.", "www&#46;", escaped)
    if escaped.startswith(("-", "+", ">")):
        escaped = f"\\{escaped}"
    escaped = re.sub(r"^(\d+)\.", r"\1\\.", escaped)
    return escaped


def _issue_title(priority: str, title: str) -> str:
    safe_title = " ".join(title.split()).replace("@", "＠")
    result = f"[Advisor][{priority}] {safe_title}"
    if len(result) > 256:
        raise PolicyError("issue title exceeds 256 characters")
    return result


def _fingerprint_parts(fingerprint: str) -> tuple[str, str]:
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise PolicyError("published recommendation has an invalid fingerprint")
    digest = fingerprint.removeprefix("fp_")
    return (
        f"advisor:fp:{digest}",
        f"<!-- infra-fleet-advisor-fingerprint: {fingerprint} -->",
    )


def _evidence_is_secret_safe(evidence: Evidence) -> bool:
    values = (
        evidence.evidence_id,
        evidence.kind,
        evidence.source_path,
        evidence.locator,
        evidence.excerpt,
        *evidence.fact.keys(),
        *(value for value in evidence.fact.values() if isinstance(value, str)),
    )
    return not any(contains_secret(value) for value in values)


def _evidence_markdown(evidence: Evidence, source_sha: str) -> str:
    source_url = (
        f"https://github.com/{FLEET_REPOSITORY}/blob/{source_sha}/"
        f"{quote(evidence.source_path, safe='/')}"
    )
    fact = json.dumps(dict(evidence.fact), sort_keys=True, separators=(",", ":"))
    return "\n".join(
        (
            f"- [{_safe_text(evidence.source_path)}]({source_url})",
            f"  - Locator: {_safe_text(evidence.locator)}",
            f"  - Evidence ID: {_safe_text(evidence.evidence_id)}",
            f"  - Fact: {_safe_text(fact)}",
            f"  - Captured excerpt: {_safe_text(evidence.excerpt)}",
        )
    )


def _active_issue_body(
    *,
    fingerprint: str,
    marker: str,
    source_sha: str,
    category: str,
    summary: str,
    impact: str,
    suggested_change: str,
    trade_offs: str,
    confidence: float,
    confidence_explanation: str,
    evidence: tuple[Evidence, ...],
) -> str:
    source_url = f"https://github.com/{FLEET_REPOSITORY}/commit/{source_sha}"
    evidence_text = "\n".join(_evidence_markdown(item, source_sha) for item in evidence)
    body = "\n".join(
        (
            marker,
            "",
            "Generated from a merged Infra Fleet Advisor report. This is an unexecuted",
            "recommendation; closing or changing this issue remains a human decision.",
            "",
            f"- Source: [{source_sha[:7]}]({source_url})",
            f"- Category: {_safe_text(category)}",
            f"- Fingerprint: {_safe_text(fingerprint)}",
            f"- Confidence: {confidence:.2f} — {_safe_text(confidence_explanation)}",
            "",
            "## Recommendation",
            "",
            _safe_text(summary),
            "",
            f"**Expected impact:** {_safe_text(impact)}",
            "",
            f"**Suggested change:** {_safe_text(suggested_change)}",
            "",
            f"**Trade-offs:** {_safe_text(trade_offs)}",
            "",
            "## Verified repository evidence",
            "",
            evidence_text,
            "",
            "The evidence above is desired state captured from the named Git commit; it is",
            "not a claim about live AWS or Kubernetes state.",
        )
    )
    if len(body) > MAX_ISSUE_BODY_CHARS:
        raise PolicyError(f"issue body exceeds {MAX_ISSUE_BODY_CHARS} characters")
    return body


def _resolution_text(fingerprint: str, source_sha: str) -> tuple[str, str]:
    marker = f"<!-- infra-fleet-advisor-resolution: {fingerprint} -->"
    source_url = f"https://github.com/{FLEET_REPOSITORY}/commit/{source_sha}"
    comment = "\n".join(
        (
            marker,
            "",
            f"The advisor no longer detected this evidence at [{source_sha[:7]}]({source_url}).",
            "This does not prove the underlying risk is gone, so the issue has not been",
            "closed or otherwise changed. A maintainer should make that decision.",
        )
    )
    return marker, comment


def build_issue_plan(report_path: Path, policy_path: Path) -> IssuePlan:
    """Revalidate a merged report and derive bounded, inert GitHub issue actions."""
    metadata = read_report_metadata(report_path)
    if metadata.source_label != FLEET_SOURCE_LABEL:
        raise PolicyError("report source is not the configured fleet")
    if not _FULL_SHA.fullmatch(metadata.source_commit_sha):
        raise PolicyError("report source commit must be a full lowercase Git SHA")

    policy = load_policy(policy_path, TAXONOMY)
    if metadata.policy_version != policy.version:
        raise PolicyError("report policy version does not match the current policy")
    bounds = policy.to_bounds()
    report = load_prior_report(report_path)
    if report is None:
        raise PolicyError("no published report to turn into issues")

    actions: list[IssueAction] = []
    seen_fingerprints: set[str] = set()
    for recommendation in report.recommendations:
        if recommendation.fingerprint in seen_fingerprints:
            raise PolicyError("published report contains a duplicate fingerprint")
        seen_fingerprints.add(recommendation.fingerprint)

        if not is_prior_recommendation_valid(
            recommendation, bounds, CONCERN_RULES, report.evidence_by_id
        ):
            raise PolicyError("published report contains an invalid recommendation")
        expected_fingerprint = compute_fingerprint(
            recommendation.category,
            recommendation.concern_key,
            recommendation.evidence_ids,
        )
        if recommendation.fingerprint != expected_fingerprint:
            raise PolicyError("published recommendation fingerprint does not match its evidence")

        expected_trade_off = bounds.accepted_trade_offs.get(recommendation.concern_key)
        if recommendation.owner_accepted_trade_off != expected_trade_off:
            raise PolicyError("report trade-off does not match the current policy")
        concern_is_suppressed = recommendation.concern_key in bounds.suppressed_concerns
        if (recommendation.status == "suppressed") != concern_is_suppressed:
            raise PolicyError("report suppression status does not match the current policy")
        if recommendation.status == "suppressed" or expected_trade_off is not None:
            continue

        cited_evidence = tuple(
            report.evidence_by_id[evidence_id] for evidence_id in recommendation.evidence_ids
        )
        if any(not _evidence_is_secret_safe(item) for item in cited_evidence):
            raise PolicyError("published evidence contains a secret-like value")

        label, fingerprint_marker = _fingerprint_parts(recommendation.fingerprint)
        resolution_marker, resolution_comment = _resolution_text(
            recommendation.fingerprint, metadata.source_commit_sha
        )
        action: Literal["active", "resolved"] = (
            "resolved" if recommendation.status == "resolved" else "active"
        )
        body = (
            ""
            if action == "resolved"
            else _active_issue_body(
                fingerprint=recommendation.fingerprint,
                marker=fingerprint_marker,
                source_sha=metadata.source_commit_sha,
                category=recommendation.category,
                summary=recommendation.summary,
                impact=recommendation.impact,
                suggested_change=recommendation.suggested_change,
                trade_offs=recommendation.trade_offs,
                confidence=recommendation.confidence,
                confidence_explanation=recommendation.confidence_explanation,
                evidence=cited_evidence,
            )
        )
        actions.append(
            IssueAction(
                action=action,
                fingerprint=recommendation.fingerprint,
                concern_key=recommendation.concern_key,
                fingerprint_label=label,
                fingerprint_marker=fingerprint_marker,
                title=_issue_title(recommendation.priority, recommendation.title),
                body=body,
                resolution_marker=resolution_marker,
                resolution_comment=resolution_comment,
            )
        )

    if len(actions) > MAX_ISSUE_ACTIONS:
        raise PolicyError(f"issue plan exceeds {MAX_ISSUE_ACTIONS} actions")
    actions.sort(key=lambda item: item.fingerprint)
    return IssuePlan(
        target_repository=FLEET_REPOSITORY,
        source_commit_sha=metadata.source_commit_sha,
        actions=tuple(actions),
    )


def write_issue_plan(plan: IssuePlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(asdict(plan), sort_keys=True, indent=2))
