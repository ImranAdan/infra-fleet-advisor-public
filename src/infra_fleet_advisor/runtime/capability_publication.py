import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from infra_fleet_advisor.config.intents import (
    MAX_INTENT_PROPOSITIONS,
    IntentCatalog,
    IntentProposition,
    load_intent_catalog,
)
from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.config.policy import AdvisorPolicy
from infra_fleet_advisor.core.contracts import PRIORITIES
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.intent import IntentEvaluation, IntentEvaluationStatus
from infra_fleet_advisor.runtime.github_issues import (
    GitHubIssueClient,
    IssuePublicationProfile,
    PublicationResult,
    publish_issue_actions,
)
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_SOURCE_LABEL,
    IssueAction,
)
from infra_fleet_advisor.runtime.report_writer import (
    MAX_PRIOR_REPORT_BYTES,
    read_report_metadata,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import CONCERN_TEMPLATES
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import INTENT_CHECKS

ADVISOR_REPOSITORY = "ImranAdan/infra-fleet-advisor-public"
CAPABILITY_GAP_LABEL = "intent-capability-gap"
MAX_CAPABILITY_BODY_CHARS = 20_000
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_EVALUATION_FIELDS = frozenset(
    {
        "document_id",
        "proposition_id",
        "category",
        "priority",
        "statement",
        "check_key",
        "status",
        "evidence_ids",
        "reason",
    }
)
_REASON_STATUS = {
    "check_not_declared": "declared_unverified",
    "check_not_registered": "declared_unverified",
    "category_not_enabled_by_policy": "declared_unverified",
    "collector_not_run": "declared_unverified",
    "collector_incomplete": "declared_unverified",
    "no_relevant_evidence": "declared_unverified",
    "collector_cannot_prove_satisfaction": "declared_unverified",
    "evidence_conflicts_with_intent": "divergent",
    "complete_evidence_supports_intent": "satisfied",
}
_ACTIONABLE_GAP_REASONS = frozenset(
    reason for reason in _REASON_STATUS if reason != "category_not_enabled_by_policy"
) - frozenset({"evidence_conflicts_with_intent", "complete_evidence_supports_intent"})
_GAP_GUIDANCE = {
    "check_not_declared": (
        "Determine whether an existing registered check exactly represents this position. "
        "If not, add the smallest bounded collector and check needed to verify it."
    ),
    "check_not_registered": (
        "Implement the declared check through the trusted registry, backed by typed repository "
        "evidence and a deterministic support predicate."
    ),
    "collector_not_run": (
        "Bind the registered collector into the repository-review composition and preserve "
        "explicit failed or partial coverage."
    ),
    "collector_incomplete": (
        "Make the relevant collector complete for this repository surface without treating "
        "missing or malformed input as healthy state."
    ),
    "no_relevant_evidence": (
        "Define deterministic applicability and absence semantics so the check can distinguish "
        "a satisfied proposition from an unobservable one."
    ),
    "collector_cannot_prove_satisfaction": (
        "Extend the evidence contract only if repository desired state can conclusively prove "
        "this position; otherwise retain an explicit documented limit."
    ),
}

CAPABILITY_ISSUE_PROFILE = IssuePublicationProfile(
    target_repository=ADVISOR_REPOSITORY,
    primary_label=CAPABILITY_GAP_LABEL,
    primary_label_color="d4c5f9",
    primary_label_description="Intent proposition awaiting deterministic advisor coverage",
    identity_label_color="c5def5",
    identity_label_description="Stable intent proposition identity",
)


@dataclass(frozen=True, slots=True)
class CapabilityPlan:
    target_repository: str
    source_commit_sha: str
    actions: tuple[IssueAction, ...]


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _parse_evaluation(raw: Any) -> IntentEvaluation:
    if not isinstance(raw, dict) or set(raw) != _EVALUATION_FIELDS:
        raise TypeError("intent evaluation must match the closed schema")
    priority = raw["priority"]
    if priority is not None and (not isinstance(priority, str) or priority not in PRIORITIES):
        raise TypeError("intent evaluation priority is invalid")
    check_key = raw["check_key"]
    if check_key is not None and not isinstance(check_key, str):
        raise TypeError("intent evaluation check key is invalid")
    evidence_ids = raw["evidence_ids"]
    if (
        not isinstance(evidence_ids, list)
        or any(not isinstance(item, str) for item in evidence_ids)
        or len(set(evidence_ids)) != len(evidence_ids)
    ):
        raise TypeError("intent evaluation evidence IDs are invalid")
    status = _require_str(raw["status"], "intent evaluation status")
    reason = _require_str(raw["reason"], "intent evaluation reason")
    if _REASON_STATUS.get(reason) != status:
        raise TypeError("intent evaluation reason and status are inconsistent")
    if (status == "divergent") != bool(evidence_ids):
        raise TypeError("only divergent intent evaluations may cite evidence")
    return IntentEvaluation(
        document_id=_require_str(raw["document_id"], "intent document id"),
        proposition_id=_require_str(raw["proposition_id"], "intent proposition id"),
        category=_require_str(raw["category"], "intent category"),
        priority=priority,
        statement=_require_str(raw["statement"], "intent statement"),
        check_key=check_key,
        status=cast(IntentEvaluationStatus, status),
        evidence_ids=tuple(evidence_ids),
        reason=reason,
    )


def _read_evaluations(report_path: Path) -> tuple[IntentEvaluation, ...]:
    try:
        if report_path.stat().st_size > MAX_PRIOR_REPORT_BYTES:
            raise PolicyError(f"report exceeds {MAX_PRIOR_REPORT_BYTES} bytes")
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        evaluations = raw["intent_evaluations"]
        if not isinstance(evaluations, list) or len(evaluations) > MAX_INTENT_PROPOSITIONS:
            raise TypeError
        return tuple(_parse_evaluation(item) for item in evaluations)
    except PolicyError:
        raise
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PolicyError(f"cannot read report intent evaluations: {type(exc).__name__}") from exc


def _expected_priority(proposition: IntentProposition, policy: AdvisorPolicy) -> str | None:
    definition = (
        INTENT_CHECKS.get(proposition.check_key) if proposition.check_key is not None else None
    )
    if definition is None or proposition.category not in policy.enabled_categories:
        return proposition.priority
    return proposition.priority or CONCERN_TEMPLATES[definition.concern_key].priority


def _validate_evaluation(
    proposition: IntentProposition,
    evaluation: IntentEvaluation,
    policy: AdvisorPolicy,
) -> None:
    if (
        evaluation.document_id != proposition.document_id
        or evaluation.proposition_id != proposition.proposition_id
        or evaluation.category != proposition.category
        or evaluation.priority != _expected_priority(proposition, policy)
        or evaluation.statement != proposition.statement
        or evaluation.check_key != proposition.check_key
    ):
        raise PolicyError("report intent evaluation does not match the current catalog")

    definition = (
        INTENT_CHECKS.get(proposition.check_key) if proposition.check_key is not None else None
    )
    if proposition.category not in policy.enabled_categories:
        expected = ("declared_unverified", "category_not_enabled_by_policy")
    elif proposition.check_key is None:
        expected = ("declared_unverified", "check_not_declared")
    elif definition is None:
        expected = ("declared_unverified", "check_not_registered")
    else:
        if proposition.category != definition.rule.category:
            raise PolicyError("intent check category does not match its trusted registry entry")
        allowed_reasons = {
            "collector_not_run",
            "collector_incomplete",
            "evidence_conflicts_with_intent",
        }
        if definition.requires_relevant_evidence:
            allowed_reasons.add("no_relevant_evidence")
        if definition.can_prove_satisfaction:
            allowed_reasons.add("complete_evidence_supports_intent")
        else:
            allowed_reasons.add("collector_cannot_prove_satisfaction")
        if evaluation.reason not in allowed_reasons:
            raise PolicyError("report contradicts the registered check capability")
        return
    if (evaluation.status, evaluation.reason) != expected:
        raise PolicyError("report intent evaluation contradicts the current catalog")


def _validated_evaluations(
    catalog: IntentCatalog,
    evaluations: tuple[IntentEvaluation, ...],
    policy: AdvisorPolicy,
) -> tuple[IntentEvaluation, ...]:
    by_identity = {(item.document_id, item.proposition_id): item for item in evaluations}
    if len(by_identity) != len(evaluations):
        raise PolicyError("report contains duplicate intent evaluation identities")
    propositions = {(item.document_id, item.proposition_id): item for item in catalog.propositions}
    if set(by_identity) != set(propositions):
        raise PolicyError("report does not contain exactly one evaluation per intent proposition")
    for identity, proposition in propositions.items():
        _validate_evaluation(proposition, by_identity[identity], policy)
    return tuple(by_identity[key] for key in sorted(by_identity))


def _safe_text(value: str) -> str:
    collapsed = " ".join(value.split())
    escaped = html.escape(collapsed, quote=False).replace("\\", "\\\\")
    for character in "`*_{}[]#":
        escaped = escaped.replace(character, f"\\{character}")
    escaped = escaped.replace("@", "&#64;")
    escaped = re.sub(r"(?i)\b(https?)://", lambda match: f"{match.group(1)}&#58;//", escaped)
    escaped = re.sub(r"(?i)\bwww\.", "www&#46;", escaped)
    if escaped.startswith(("-", "+")):
        escaped = f"\\{escaped}"
    escaped = re.sub(r"^(\d+)\.", r"\1\\.", escaped)
    return escaped


def _identity_parts(document_id: str, proposition_id: str) -> tuple[str, str, str]:
    material = f"{document_id}\0{proposition_id}".encode()
    fingerprint = f"cap_{hashlib.sha256(material).hexdigest()[:24]}"
    digest = fingerprint.removeprefix("cap_")
    return (
        fingerprint,
        f"advisor:intent:{digest}",
        f"<!-- infra-fleet-advisor-fingerprint: {fingerprint} -->",
    )


def _content_marker(evaluation: IntentEvaluation) -> str:
    material = json.dumps(
        {
            "category": evaluation.category,
            "check_key": evaluation.check_key,
            "priority": evaluation.priority,
            "reason": evaluation.reason,
            "statement": evaluation.statement,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    digest = hashlib.sha256(material).hexdigest()
    return f"<!-- infra-fleet-advisor-capability-content: {digest} -->"


def _active_body(
    evaluation: IntentEvaluation,
    fingerprint: str,
    marker: str,
    content_marker: str,
) -> str:
    guidance = _GAP_GUIDANCE[evaluation.reason]
    body = "\n".join(
        (
            marker,
            content_marker,
            "",
            "Generated from a human-ratified Infra Fleet Advisor report.",
            "",
            "This is advisor capability work, not evidence that the fleet violates the intent.",
            "No fleet issue may be created until a deterministic collector proves divergence.",
            "",
            f"- Intent: {_safe_text(evaluation.document_id)}/"
            f"{_safe_text(evaluation.proposition_id)}",
            f"- Category: {_safe_text(evaluation.category)}",
            f"- Priority: {_safe_text(evaluation.priority or 'not declared')}",
            f"- Declared check: {_safe_text(evaluation.check_key or 'not declared')}",
            f"- Evaluation gap: {_safe_text(evaluation.reason)}",
            f"- Capability fingerprint: {_safe_text(fingerprint)}",
            "",
            "## Declared position",
            "",
            _safe_text(evaluation.statement),
            "",
            "## Work required",
            "",
            _safe_text(guidance),
            "",
            "## Definition of done",
            "",
            "- Evidence is collected from the verified immutable repository snapshot.",
            "- The collector and check are explicitly registered in trusted code.",
            "- Missing, malformed, unsafe, or incomplete input cannot prove satisfaction.",
            "- Deterministic tests cover satisfied, divergent, and unverified outcomes.",
            "- A model cannot invent evidence, select tools, or make the work publishable.",
            "- A later merged report is required before any fleet issue can be emitted.",
        )
    )
    if len(body) > MAX_CAPABILITY_BODY_CHARS:
        raise PolicyError(f"capability issue body exceeds {MAX_CAPABILITY_BODY_CHARS} characters")
    return body


def _action(evaluation: IntentEvaluation) -> IssueAction:
    fingerprint, label, marker = _identity_parts(evaluation.document_id, evaluation.proposition_id)
    resolution_marker = f"<!-- infra-fleet-advisor-capability-resolution: {fingerprint} -->"
    content_marker = _content_marker(evaluation)
    is_active = (
        evaluation.status == "declared_unverified" and evaluation.reason in _ACTIONABLE_GAP_REASONS
    )
    return IssueAction(
        action="active" if is_active else "resolved",
        fingerprint=fingerprint,
        concern_key="intent_capability_gap",
        fingerprint_label=label,
        fingerprint_marker=marker,
        title=(
            f"[Intent capability][{evaluation.category}] "
            f"{evaluation.document_id}/{evaluation.proposition_id}"
        ),
        body=(_active_body(evaluation, fingerprint, marker, content_marker) if is_active else ""),
        resolution_marker=resolution_marker,
        resolution_comment="\n".join(
            (
                resolution_marker,
                "",
                "The current merged advisory report no longer classifies this proposition as an",
                "actionable evaluation gap. Issue state remains a human decision.",
            )
        ),
        intent_document_id=evaluation.document_id,
        intent_proposition_id=evaluation.proposition_id,
        content_marker=content_marker,
    )


def build_capability_plan(
    report_path: Path,
    policy_path: Path,
    intent_dir: Path,
) -> CapabilityPlan:
    """Derive bounded advisor work from a merged report without claiming fleet divergence."""
    metadata = read_report_metadata(report_path)
    if metadata.source_label != FLEET_SOURCE_LABEL:
        raise PolicyError("report source is not the configured fleet")
    if not _FULL_SHA.fullmatch(metadata.source_commit_sha):
        raise PolicyError("report source commit must be a full lowercase Git SHA")
    policy = load_policy(policy_path, TAXONOMY)
    if metadata.policy_version != policy.version:
        raise PolicyError("report policy version does not match the current policy")
    catalog = load_intent_catalog(intent_dir, TAXONOMY)
    if metadata.intent_digest != catalog.digest:
        raise PolicyError("report intent digest does not match the current intent catalog")
    evaluations = _validated_evaluations(catalog, _read_evaluations(report_path), policy)
    actions = tuple(
        sorted((_action(item) for item in evaluations), key=lambda item: item.fingerprint)
    )
    if len(actions) > MAX_INTENT_PROPOSITIONS:
        raise PolicyError(f"capability plan exceeds {MAX_INTENT_PROPOSITIONS} actions")
    return CapabilityPlan(ADVISOR_REPOSITORY, metadata.source_commit_sha, actions)


def write_capability_plan(plan: CapabilityPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(asdict(plan), sort_keys=True, indent=2))


def publish_capability_plan(
    plan: CapabilityPlan,
    client: GitHubIssueClient,
    workflow_bot_login: str,
) -> PublicationResult:
    """Reconcile capability work only inside the configured advisor repository."""
    return publish_issue_actions(
        plan.target_repository,
        plan.actions,
        client,
        workflow_bot_login,
        CAPABILITY_ISSUE_PROFILE,
    )
