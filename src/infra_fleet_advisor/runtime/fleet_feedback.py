import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from infra_fleet_advisor.config.loader import MAX_POLICY_FILE_BYTES, load_policy
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.issue_publication import build_issue_plan
from infra_fleet_advisor.runtime.report_writer import read_report_metadata
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import CONCERN_RULES
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY

ADVISOR_ISSUE_LABEL = "infra-fleet-advisor"
WONTFIX_LABEL = "advisor:wontfix"
CANCELLATION_MARKER = "<!-- infra-fleet-advisor-feedback-cancelled -->"
TRADE_OFF_LABELS = {
    "advisor:tradeoff:availability": (
        "The owner accepts the availability impact of leaving this recommendation undone."
    ),
    "advisor:tradeoff:compatibility": (
        "The owner accepts the compatibility constraint that prevents this recommendation."
    ),
    "advisor:tradeoff:complexity": (
        "The owner accepts the operational complexity avoided by not implementing "
        "this recommendation."
    ),
    "advisor:tradeoff:cost": (
        "The owner accepts the cost trade-off of leaving this recommendation undone."
    ),
    "advisor:tradeoff:risk-accepted": (
        "The owner has explicitly accepted the risk described by this recommendation."
    ),
}

_FINGERPRINT_LABEL = re.compile(r"^advisor:fp:([0-9a-f]{24})$")
_FINGERPRINT = re.compile(r"^fp_[0-9a-f]{24}$")
_SIGNATURE = re.compile(r"^v1:[0-9a-f]{64}$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_BOT_LOGIN = re.compile(r"^[A-Za-z0-9-]+\[bot\]$")
MAX_FEEDBACK_PLAN_FILE_BYTES = 256 * 1024
MAX_FEEDBACK_PR_STATE_FILE_BYTES = 16 * 1024 * 1024
MAX_FEEDBACK_ADDITIONS = 100
MAX_FEEDBACK_PR_HISTORY = 199
MAX_PR_BODY_CHARS = 65_536


@dataclass(frozen=True, slots=True)
class FleetIssueRecord:
    number: int
    state: str
    author: str
    labels: frozenset[str]


@dataclass(frozen=True, slots=True)
class FleetIssueRecords:
    issues: tuple[FleetIssueRecord, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class TradeOffAddition:
    issue_number: int
    fingerprint: str
    concern_key: str
    reason_label: str
    rationale: str


@dataclass(frozen=True, slots=True)
class FeedbackPlan:
    status: Literal["ready", "awaiting_report_refresh"]
    signature: str
    marker: str
    additions: tuple[TradeOffAddition, ...]


@dataclass(frozen=True, slots=True)
class FeedbackPullRequest:
    number: int
    state: Literal["open", "closed"]
    author: str
    body: str
    merged: bool
    head_sha: str


@dataclass(frozen=True, slots=True)
class FeedbackPublicationDecision:
    action: Literal["none", "create", "update", "cancel"]
    reason: str
    open_pr_number: int | None = None


def _feedback_plan(
    additions: tuple[TradeOffAddition, ...],
    status: Literal["ready", "awaiting_report_refresh"] = "ready",
) -> FeedbackPlan:
    canonical = json.dumps(
        {
            "additions": [asdict(item) for item in additions],
            "status": status,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = "v1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    marker = f"<!-- infra-fleet-advisor-feedback: {signature} -->"
    return FeedbackPlan(status, signature, marker, additions)


def _rationale(reason_label: str, issue_number: int) -> str:
    return (
        f"{TRADE_OFF_LABELS[reason_label]} Decision recorded from closed fleet issue "
        f"#{issue_number}; issue prose was not imported."
    )


def _read_bounded_json(path: Path, description: str, maximum_bytes: int) -> Any:
    try:
        if path.stat().st_size > maximum_bytes:
            raise PolicyError(f"{description} exceeds {maximum_bytes} bytes")
        return json.loads(path.read_text(encoding="utf-8"))
    except PolicyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {description}: {type(exc).__name__}") from exc


def read_feedback_plan(path: Path) -> FeedbackPlan:
    """Reload and authenticate a deterministic feedback plan at the workflow boundary."""
    raw = _read_bounded_json(path, "feedback plan", MAX_FEEDBACK_PLAN_FILE_BYTES)
    try:
        if not isinstance(raw, dict) or set(raw) != {
            "status",
            "signature",
            "marker",
            "additions",
        }:
            raise TypeError
        status = raw["status"]
        if status not in ("ready", "awaiting_report_refresh"):
            raise ValueError
        raw_additions = raw["additions"]
        if not isinstance(raw_additions, list) or len(raw_additions) > MAX_FEEDBACK_ADDITIONS:
            raise TypeError
        additions: list[TradeOffAddition] = []
        seen_concerns: set[str] = set()
        for item in raw_additions:
            if not isinstance(item, dict) or set(item) != {
                "issue_number",
                "fingerprint",
                "concern_key",
                "reason_label",
                "rationale",
            }:
                raise TypeError
            issue_number = item["issue_number"]
            fingerprint = item["fingerprint"]
            concern_key = item["concern_key"]
            reason_label = item["reason_label"]
            rationale = item["rationale"]
            if (
                not isinstance(issue_number, int)
                or isinstance(issue_number, bool)
                or issue_number < 1
                or not isinstance(fingerprint, str)
                or not _FINGERPRINT.fullmatch(fingerprint)
                or not isinstance(concern_key, str)
                or concern_key not in CONCERN_RULES
                or concern_key in seen_concerns
                or not isinstance(reason_label, str)
                or reason_label not in TRADE_OFF_LABELS
                or not isinstance(rationale, str)
                or rationale != _rationale(reason_label, issue_number)
            ):
                raise ValueError
            seen_concerns.add(concern_key)
            additions.append(
                TradeOffAddition(
                    issue_number,
                    fingerprint,
                    concern_key,
                    reason_label,
                    rationale,
                )
            )
        if status == "awaiting_report_refresh" and additions:
            raise ValueError
        additions.sort(key=lambda item: (item.concern_key, item.issue_number))
        expected = _feedback_plan(tuple(additions), status)
        if (
            not isinstance(raw["signature"], str)
            or not _SIGNATURE.fullmatch(raw["signature"])
            or raw["signature"] != expected.signature
            or raw["marker"] != expected.marker
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyError("feedback plan failed deterministic validation") from exc
    return expected


def read_feedback_pull_requests(
    path: Path,
    *,
    repository: str,
    branch: str,
    maximum: int,
) -> tuple[FeedbackPullRequest, ...]:
    """Project untrusted GitHub PR JSON into the fields used for lifecycle decisions."""
    raw = _read_bounded_json(
        path,
        "feedback pull request state",
        MAX_FEEDBACK_PR_STATE_FILE_BYTES,
    )
    try:
        if not isinstance(raw, list) or len(raw) > maximum:
            raise TypeError
        records: list[FeedbackPullRequest] = []
        for item in raw:
            if not isinstance(item, dict):
                raise TypeError
            number = item["number"]
            state = item["state"]
            author = item["user"]["login"]
            body = item.get("body") or ""
            head_repository = item["head"]["repo"]["full_name"]
            head_branch = item["head"]["ref"]
            head_sha = item["head"]["sha"]
            base_repository = item["base"]["repo"]["full_name"]
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
                or state not in ("open", "closed")
                or not isinstance(author, str)
                or not isinstance(body, str)
                or len(body) > MAX_PR_BODY_CHARS
                or not isinstance(head_repository, str)
                or head_repository.casefold() != repository.casefold()
                or head_branch != branch
                or not isinstance(head_sha, str)
                or not _FULL_SHA.fullmatch(head_sha)
                or not isinstance(base_repository, str)
                or base_repository.casefold() != repository.casefold()
            ):
                raise ValueError
            merged = item.get("merged_at") is not None
            if state == "open" and merged:
                raise ValueError
            records.append(FeedbackPullRequest(number, state, author, body, merged, head_sha))
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyError("feedback pull request state failed validation") from exc
    return tuple(records)


def _has_exact_marker(body: str, marker: str) -> bool:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return marker in normalized.split("\n")


def decide_feedback_publication(
    plan: FeedbackPlan,
    open_prs: tuple[FeedbackPullRequest, ...],
    history_prs: tuple[FeedbackPullRequest, ...],
    *,
    branch_tip: str | None,
    branch_is_recoverable: bool = False,
    workflow_bot_login: str = "github-actions[bot]",
) -> FeedbackPublicationDecision:
    """Choose one bounded PR transition without trusting PR prose."""
    if not _BOT_LOGIN.fullmatch(workflow_bot_login):
        raise PolicyError("invalid workflow bot login")
    if branch_tip is not None and not _FULL_SHA.fullmatch(branch_tip):
        raise PolicyError("invalid feedback branch tip")
    if branch_is_recoverable and branch_tip is None:
        raise PolicyError("a missing feedback branch cannot be recoverable")
    if len(open_prs) > 1 or len(history_prs) > MAX_FEEDBACK_PR_HISTORY:
        raise PolicyError("feedback pull request history exceeds its bound")
    if len({pull.number for pull in history_prs}) != len(history_prs):
        raise PolicyError("feedback pull request history contains duplicate records")
    open_pr = open_prs[0] if open_prs else None
    latest_pr = max(history_prs, key=lambda pull: pull.number) if history_prs else None
    if open_pr is not None and (
        open_pr.state != "open" or open_pr.author.casefold() != workflow_bot_login.casefold()
    ):
        raise PolicyError("open feedback pull request is not workflow-owned")
    if not plan.additions:
        if open_pr is None:
            return FeedbackPublicationDecision("none", "no_feedback")
        return FeedbackPublicationDecision("cancel", "feedback_revoked", open_pr.number)

    if branch_tip is not None:
        latest_matches_branch = (
            latest_pr is not None
            and latest_pr.author.casefold() == workflow_bot_login.casefold()
            and latest_pr.head_sha == branch_tip
        )
        if not latest_matches_branch and not (open_pr is None and branch_is_recoverable):
            raise PolicyError("feedback branch cannot be proven workflow-owned")

    if (
        open_pr is not None
        and branch_tip is not None
        and _has_exact_marker(open_pr.body, plan.marker)
        and not _has_exact_marker(open_pr.body, CANCELLATION_MARKER)
    ):
        return FeedbackPublicationDecision("none", "already_open", open_pr.number)

    matching_history = tuple(
        pull
        for pull in history_prs
        if pull.author.casefold() == workflow_bot_login.casefold()
        and _has_exact_marker(pull.body, plan.marker)
    )
    if matching_history:
        latest_match = max(matching_history, key=lambda pull: pull.number)
        if (
            latest_match.state == "closed"
            and not latest_match.merged
            and not _has_exact_marker(latest_match.body, CANCELLATION_MARKER)
        ):
            return FeedbackPublicationDecision("none", "declined", latest_match.number)

    if open_pr is not None:
        return FeedbackPublicationDecision("update", "feedback_changed", open_pr.number)
    return FeedbackPublicationDecision("create", "new_feedback")


def build_feedback_plan(
    report_path: Path,
    policy_path: Path,
    records: FleetIssueRecords,
    app_bot_login: str,
) -> FeedbackPlan:
    """Convert closed, bot-authored label decisions into policy additions."""
    if not records.complete:
        raise PolicyError("fleet issue listing exceeded the feedback bound")
    if not _BOT_LOGIN.fullmatch(app_bot_login):
        raise PolicyError("invalid GitHub App bot login")

    metadata = read_report_metadata(report_path)
    policy = load_policy(policy_path, TAXONOMY)
    if metadata.policy_version != policy.version:
        return _feedback_plan((), "awaiting_report_refresh")

    issue_plan = build_issue_plan(report_path, policy_path)
    active_actions = {
        action.fingerprint: action for action in issue_plan.actions if action.action == "active"
    }
    concern_counts: dict[str, int] = {}
    for active_action in active_actions.values():
        concern_counts[active_action.concern_key] = (
            concern_counts.get(active_action.concern_key, 0) + 1
        )

    additions: list[TradeOffAddition] = []
    seen_concerns: set[str] = set()
    for issue in records.issues:
        if issue.author.casefold() != app_bot_login.casefold():
            continue
        if ADVISOR_ISSUE_LABEL not in issue.labels or WONTFIX_LABEL not in issue.labels:
            continue
        if issue.state != "closed":
            continue

        fingerprint_labels = tuple(
            label for label in issue.labels if _FINGERPRINT_LABEL.fullmatch(label)
        )
        if len(fingerprint_labels) != 1:
            continue
        match = _FINGERPRINT_LABEL.fullmatch(fingerprint_labels[0])
        assert match is not None
        fingerprint = f"fp_{match.group(1)}"
        matched_action = active_actions.get(fingerprint)
        if matched_action is None:
            continue
        reason_labels = tuple(label for label in issue.labels if label in TRADE_OFF_LABELS)
        if len(reason_labels) != 1:
            continue
        if concern_counts[matched_action.concern_key] != 1:
            raise PolicyError(
                "wontfix feedback is ambiguous for a concern with multiple active findings"
            )
        if matched_action.concern_key in seen_concerns:
            raise PolicyError("multiple wontfix issues map to one policy concern")
        seen_concerns.add(matched_action.concern_key)
        reason_label = reason_labels[0]
        rationale = _rationale(reason_label, issue.number)
        additions.append(
            TradeOffAddition(
                issue_number=issue.number,
                fingerprint=fingerprint,
                concern_key=matched_action.concern_key,
                reason_label=reason_label,
                rationale=rationale,
            )
        )

    additions.sort(key=lambda item: (item.concern_key, item.issue_number))
    return _feedback_plan(tuple(additions))


def _updated_policy_text(policy_path: Path, plan: FeedbackPlan) -> str:
    try:
        if policy_path.stat().st_size > MAX_POLICY_FILE_BYTES:
            raise PolicyError(f"policy file exceeds {MAX_POLICY_FILE_BYTES} bytes")
        text = policy_path.read_text(encoding="utf-8")
    except PolicyError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PolicyError(f"cannot read policy for feedback: {type(exc).__name__}") from exc

    entries = "\n".join(
        "\n".join(
            (
                f"  - concern_key: {item.concern_key}",
                f"    rationale: {json.dumps(item.rationale)}",
            )
        )
        for item in plan.additions
    )
    empty_pattern = re.compile(r"^accepted_trade_offs:[ \t]*\[\][ \t]*$", re.MULTILINE)
    if empty_pattern.search(text):
        updated = empty_pattern.sub(
            lambda _: f"accepted_trade_offs:\n{entries}",
            text,
            count=1,
        )
    else:
        header = re.search(r"^accepted_trade_offs:[ \t]*$", text, re.MULTILINE)
        if header is None:
            raise PolicyError("policy accepted_trade_offs block is not safely editable")
        block_start = header.end()
        if text.startswith("\r\n", block_start):
            block_start += 2
        elif text.startswith("\n", block_start):
            block_start += 1
        else:
            raise PolicyError("policy accepted_trade_offs block is not safely editable")

        insertion = block_start
        cursor = block_start
        for line in text[block_start:].splitlines(keepends=True):
            if line.strip() and not line[:1].isspace():
                break
            cursor += len(line)
            if line.strip():
                insertion = cursor
        prefix = text[:insertion]
        suffix = text[insertion:].lstrip("\r\n")
        entry_prefix = "" if prefix.endswith(("\n", "\r")) else "\n"
        separator = "\n\n" if suffix else "\n"
        updated = f"{prefix}{entry_prefix}{entries}{separator}{suffix}"

    prior_version = load_policy(policy_path, TAXONOMY).version
    version_material = f"{prior_version}\0{plan.signature}".encode()
    next_version = "feedback-v1:" + hashlib.sha256(version_material).hexdigest()[:24]
    version_line = re.compile(r"^version:\s*.+$", re.MULTILINE)
    if len(version_line.findall(updated)) != 1:
        raise PolicyError("policy version line is not safely editable")
    return version_line.sub(f"version: {json.dumps(next_version)}", updated, count=1)


def write_feedback_outputs(
    plan: FeedbackPlan,
    policy_path: Path,
    output_policy: Path,
    output_plan: Path,
) -> None:
    """Write reviewable outputs exclusively, then validate the resulting policy."""
    output_plan.parent.mkdir(parents=True, exist_ok=True)
    with output_plan.open("x", encoding="utf-8") as output:
        output.write(json.dumps(asdict(plan), sort_keys=True, indent=2))
    if not plan.additions:
        return
    updated = _updated_policy_text(policy_path, plan)
    output_policy.parent.mkdir(parents=True, exist_ok=True)
    with output_policy.open("x", encoding="utf-8") as output:
        output.write(updated)
    validated = load_policy(output_policy, TAXONOMY)
    expected = {item.concern_key: item.rationale for item in plan.additions}
    actual = {item.concern_key: item.rationale for item in validated.accepted_trade_offs}
    if not all(actual.get(key) == rationale for key, rationale in expected.items()):
        raise PolicyError("updated feedback policy did not preserve every decision")
