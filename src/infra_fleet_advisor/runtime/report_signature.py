import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from infra_fleet_advisor.core.contracts import STATUSES
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.report_writer import MAX_PRIOR_REPORT_BYTES

SIGNATURE_VERSION = "v2"
MAX_DECLINED_PR_BODY_BYTES = 128 * 1024
MAX_ADVISORY_PR_HISTORY = 199
MAX_ADVISORY_PR_HISTORY_FILE_BYTES = 16 * 1024 * 1024
_SIGNATURE_PATTERN = re.compile(rf"^{SIGNATURE_VERSION}:[0-9a-f]{{64}}$")


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    decision: Literal["changed", "unchanged", "declined"]
    signature: str
    marker: str


@dataclass(frozen=True, slots=True)
class _AdvisoryPullRequest:
    number: int
    body: str
    merged: bool


def _require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _read_report(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_PRIOR_REPORT_BYTES:
            raise PolicyError(f"report exceeds {MAX_PRIOR_REPORT_BYTES} bytes")
        return _require_dict(json.loads(path.read_text(encoding="utf-8")), "report")
    except PolicyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise PolicyError(f"cannot compute report signature: {type(exc).__name__}") from exc


def _signature_payload(report: dict[str, Any]) -> dict[str, Any]:
    provenance = _require_dict(report.get("provenance"), "provenance")
    findings: list[dict[str, str]] = []
    for item in _require_list(report.get("recommendations"), "recommendations"):
        recommendation = _require_dict(item, "recommendation")
        status = _require_str(recommendation.get("status"), "recommendation.status")
        if status not in STATUSES:
            raise TypeError("recommendation.status is not recognized")
        trade_off = recommendation.get("owner_accepted_trade_off")
        if trade_off is not None and not isinstance(trade_off, str):
            raise TypeError("recommendation.owner_accepted_trade_off must be a string or null")
        findings.append(
            {
                "fingerprint": _require_str(
                    recommendation.get("fingerprint"), "recommendation.fingerprint"
                ),
                "status": "open" if status in ("new", "unchanged") else status,
                "owner_accepted_trade_off": trade_off or "",
            }
        )
    findings.sort(
        key=lambda item: (
            item["fingerprint"],
            item["status"],
            item["owner_accepted_trade_off"],
        )
    )

    evidence: list[dict[str, Any]] = []
    for item in _require_list(report.get("evidence"), "evidence"):
        record = _require_dict(item, "evidence record")
        evidence.append(
            {
                "id": _require_str(record.get("evidence_id"), "evidence.evidence_id"),
                "kind": _require_str(record.get("kind"), "evidence.kind"),
                "source_path": _require_str(record.get("source_path"), "evidence.source_path"),
                "locator": _require_str(record.get("locator"), "evidence.locator"),
                "fact": _require_dict(record.get("fact"), "evidence.fact"),
                "excerpt": _require_str(record.get("excerpt"), "evidence.excerpt"),
            }
        )
    evidence.sort(key=lambda item: item["id"])

    coverage: list[dict[str, str | int | None]] = []
    for item in _require_list(report.get("coverage"), "coverage"):
        record = _require_dict(item, "coverage record")
        status = _require_str(record.get("status"), "coverage.status")
        if status not in ("ok", "partial", "failed"):
            raise TypeError("coverage.status is not recognized")
        error_summary = record.get("error_summary")
        if error_summary is not None and not isinstance(error_summary, str):
            raise TypeError("coverage.error_summary must be a string or null")
        coverage.append(
            {
                "collector_id": _require_str(record.get("collector_id"), "coverage.collector_id"),
                "status": status,
                "evidence_count": _require_int(
                    record.get("evidence_count"), "coverage.evidence_count"
                ),
                "error_summary": error_summary,
            }
        )
    coverage.sort(key=lambda item: str(item["collector_id"]))

    rejections: list[str] = []
    for item in _require_list(report.get("rejected", []), "rejected"):
        rejection = _require_dict(item, "rejected candidate")
        rejections.append(_require_str(rejection.get("reason"), "rejected.reason"))
    rejections.sort()

    return {
        "policy_version": _require_str(
            provenance.get("policy_version"), "provenance.policy_version"
        ),
        "findings": findings,
        "evidence": evidence,
        "coverage": coverage,
        "rejections": rejections,
    }


def compute_report_signature(path: Path) -> str:
    """Hash only material, deterministic report fields used for publication.

    Narrative, ranks, timestamps, and the new/unchanged lifecycle transition are
    deliberately excluded so model wording and repeated runs do not create work.
    """
    try:
        payload = _signature_payload(_read_report(path))
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyError(f"cannot compute report signature: {type(exc).__name__}") from exc
    return f"{SIGNATURE_VERSION}:{hashlib.sha256(canonical).hexdigest()}"


def decline_marker(signature: str) -> str:
    """Return the inert, exact PR-body marker used as a decline record."""
    if not _SIGNATURE_PATTERN.fullmatch(signature):
        raise ValueError("invalid report signature")
    return f"<!-- infra-fleet-advisor-report-signature: {signature} -->"


def body_records_decline(body: str, signature: str) -> bool:
    """PR prose is untrusted; only an exact, code-generated marker is read."""
    marker = decline_marker(signature)
    normalized_lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return marker in normalized_lines


def read_declined_pr_body(path: Path) -> str:
    """Read one bounded PR body without including its content or path in errors."""
    try:
        if path.stat().st_size > MAX_DECLINED_PR_BODY_BYTES:
            raise PolicyError(
                f"declined pull request body exceeds {MAX_DECLINED_PR_BODY_BYTES} bytes"
            )
        return path.read_text(encoding="utf-8")
    except PolicyError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PolicyError(f"cannot read declined pull request body: {type(exc).__name__}") from exc


def read_latest_declined_pr_body(
    path: Path,
    *,
    repository: str,
    branch: str,
    workflow_bot_login: str = "github-actions[bot]",
) -> str:
    """Select the latest workflow-owned decision from bounded PR history."""
    try:
        if path.stat().st_size > MAX_ADVISORY_PR_HISTORY_FILE_BYTES:
            raise PolicyError(
                f"advisory pull request history exceeds {MAX_ADVISORY_PR_HISTORY_FILE_BYTES} bytes"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or len(raw) > MAX_ADVISORY_PR_HISTORY:
            raise TypeError

        workflow_pull_requests: list[_AdvisoryPullRequest] = []
        seen_numbers: set[int] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise TypeError
            number = item["number"]
            state = item["state"]
            author = item["user"]["login"]
            raw_body = item.get("body")
            body = "" if raw_body is None else raw_body
            merged_at = item.get("merged_at")
            head_repository = item["head"]["repo"]["full_name"]
            head_branch = item["head"]["ref"]
            base_repository = item["base"]["repo"]["full_name"]
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
                or number in seen_numbers
                or state != "closed"
                or not isinstance(author, str)
                or not isinstance(body, str)
                or len(body.encode("utf-8")) > MAX_DECLINED_PR_BODY_BYTES
                or (merged_at is not None and not isinstance(merged_at, str))
                or not isinstance(head_repository, str)
                or head_repository.casefold() != repository.casefold()
                or head_branch != branch
                or not isinstance(base_repository, str)
                or base_repository.casefold() != repository.casefold()
            ):
                raise ValueError
            seen_numbers.add(number)
            if author.casefold() == workflow_bot_login.casefold():
                workflow_pull_requests.append(
                    _AdvisoryPullRequest(number, body, merged_at is not None)
                )
    except PolicyError:
        raise
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PolicyError("advisory pull request history failed validation") from exc

    if not workflow_pull_requests:
        return ""
    latest = max(workflow_pull_requests, key=lambda pull: pull.number)
    return "" if latest.merged else latest.body


def decide_publication(
    report: Path,
    *,
    prior_report: Path | None = None,
    latest_declined_pr_body: str = "",
) -> PublicationDecision:
    """Compare accepted state first, then the latest explicit decline record."""
    signature = compute_report_signature(report)
    marker = decline_marker(signature)
    if prior_report is not None and signature == compute_report_signature(prior_report):
        return PublicationDecision("unchanged", signature, marker)
    if body_records_decline(latest_declined_pr_body, signature):
        return PublicationDecision("declined", signature, marker)
    return PublicationDecision("changed", signature, marker)
