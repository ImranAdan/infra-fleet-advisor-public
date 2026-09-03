import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from infra_fleet_advisor.core.contracts import STATUSES
from infra_fleet_advisor.core.errors import PolicyError, UnsafePathError
from infra_fleet_advisor.core.evidence import MAX_EXCERPT_LENGTH, Evidence
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.paths import validate_repo_relative_path
from infra_fleet_advisor.core.report import Report

MAX_PRIOR_REPORT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    source_commit_sha: str
    source_label: str
    policy_version: str


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _parse_prior_recommendation(r: dict[str, Any]) -> PriorRecommendation:
    evidence_ids = r["evidence_ids"]
    if not isinstance(evidence_ids, list) or any(not isinstance(e, str) for e in evidence_ids):
        raise TypeError("evidence_ids must be a list of strings")
    confidence = r["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise TypeError("confidence must be a number")
    status = _require_str(r.get("status", "new"), "status")
    if status not in STATUSES:
        raise TypeError("status is not recognized")
    owner_accepted_trade_off = r.get("owner_accepted_trade_off")
    if owner_accepted_trade_off is not None and not isinstance(owner_accepted_trade_off, str):
        raise TypeError("owner_accepted_trade_off must be a string or null")
    return PriorRecommendation(
        fingerprint=_require_str(r["fingerprint"], "fingerprint"),
        concern_key=_require_str(r["concern_key"], "concern_key"),
        category=_require_str(r["category"], "category"),
        priority=_require_str(r["priority"], "priority"),
        title=_require_str(r["title"], "title"),
        summary=_require_str(r["summary"], "summary"),
        evidence_ids=tuple(evidence_ids),
        impact=_require_str(r["impact"], "impact"),
        suggested_change=_require_str(r["suggested_change"], "suggested_change"),
        trade_offs=_require_str(r["trade_offs"], "trade_offs"),
        confidence=confidence,
        confidence_explanation=_require_str(r["confidence_explanation"], "confidence_explanation"),
        status=status,
        owner_accepted_trade_off=owner_accepted_trade_off,
    )


def _parse_prior_evidence(e: dict[str, Any]) -> Evidence:
    fact = e.get("fact")
    if not isinstance(fact, dict) or any(
        not isinstance(key, str) or not isinstance(value, (bool, str, int))
        for key, value in fact.items()
    ):
        raise TypeError("evidence fact must map strings to bool, string, or integer values")
    return Evidence(
        evidence_id=_require_str(e["evidence_id"], "evidence_id"),
        kind=_require_str(e["kind"], "kind"),
        source_path=validate_repo_relative_path(_require_str(e["source_path"], "source_path")),
        locator=_require_str(e["locator"], "locator"),
        excerpt=_require_str(e["excerpt"], "excerpt")[:MAX_EXCERPT_LENGTH],
        fact=fact,
        collector_id=_require_str(e.get("collector_id", ""), "collector_id"),
        collector_version=_require_str(e.get("collector_version", ""), "collector_version"),
    )


def to_json(report: Report) -> str:
    return json.dumps(asdict(report), sort_keys=True, indent=2)


def to_markdown(report: Report) -> str:
    p = report.provenance
    lines = [
        "# Infra Fleet Advisor report",
        "",
        f"- Source: `{p.source_label}` @ `{p.source_commit_sha}`",
        f"- Advisor version: `{p.advisor_version}` · Policy version: `{p.policy_version}`",
        f"- Model: `{p.model_identifier}` · Run started: `{p.run_started_at}`",
        (
            f"- Lifecycle: {report.new_count} new, {report.unchanged_count} unchanged, "
            f"{report.resolved_count} resolved, {report.suppressed_count} suppressed "
            f"({report.rejected_count} rejected)"
        ),
        "",
        "## Collector coverage",
        "",
    ]
    for c in report.coverage:
        lines.append(
            f"- `{c.collector_id}`: {c.status} ({c.evidence_count} evidence)"
            + (f" — {c.error_summary}" if c.error_summary else "")
        )

    lines += ["", "## Recommendations", ""]
    for r in report.recommendations:
        rank = f"#{r.rank} " if r.rank is not None else ""
        lines.append(f"### {rank}[{r.status}] {r.title}")
        lines += [
            "",
            f"- Category: `{r.category}` · Priority: `{r.priority}` · "
            f"Confidence: {r.confidence:.2f}",
            f"- Fingerprint: `{r.fingerprint}`",
            f"- Evidence: {', '.join(f'`{e}`' for e in r.evidence_ids)}",
            "",
            r.summary,
            "",
            f"**Impact:** {r.impact}",
            "",
            f"**Suggested change:** {r.suggested_change}",
            "",
            f"**Trade-offs:** {r.trade_offs}",
            "",
        ]
        if r.owner_accepted_trade_off:
            lines += [f"**Owner-accepted trade-off:** {r.owner_accepted_trade_off}", ""]

    if report.rejected:
        # Rejections are a health signal about the synthesizer, not advice. A run
        # that starts refusing candidates is drifting, and the count alone does
        # not say why.
        lines += ["", "## Rejected candidates", ""]
        for rc in report.rejected:
            lines.append(f"- `{rc.concern_key}` (`{rc.category}`) — {rc.reason}")
        lines.append("")
    return "\n".join(lines)


def write_report(report: Report, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


def read_report_metadata(path: Path) -> ReportMetadata:
    """Read the provenance fields needed by deterministic report consumers."""
    try:
        if path.stat().st_size > MAX_PRIOR_REPORT_BYTES:
            raise PolicyError(f"report exceeds {MAX_PRIOR_REPORT_BYTES} bytes")
        raw = json.loads(path.read_text(encoding="utf-8"))
        provenance = raw["provenance"]
        return ReportMetadata(
            source_commit_sha=_require_str(provenance["source_commit_sha"], "source_commit_sha"),
            source_label=_require_str(provenance["source_label"], "source_label"),
            policy_version=_require_str(provenance["policy_version"], "policy_version"),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PolicyError(f"cannot read report provenance: {type(exc).__name__}") from exc


def read_report_source_sha(path: Path) -> str:
    """The commit the report's evidence was collected from. Anything acting on a
    report must check the tree it is about to touch is that same commit."""
    return read_report_metadata(path).source_commit_sha


def load_prior_report(path: Path | None) -> PriorReport | None:
    if path is None:
        return None
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PolicyError(f"cannot read prior report: {exc}") from exc
    if size > MAX_PRIOR_REPORT_BYTES:
        raise PolicyError(f"prior report exceeds {MAX_PRIOR_REPORT_BYTES} bytes")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        recs = [_parse_prior_recommendation(r) for r in raw["recommendations"]]
        evidence = [_parse_prior_evidence(e) for e in raw.get("evidence", [])]
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise TypeError("duplicate evidence_id")
    except UnsafePathError as exc:
        raise PolicyError("malformed prior report: unsafe evidence path") from exc
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
        ValueError,
    ) as exc:
        raise PolicyError(f"malformed prior report: {exc}") from exc
    return PriorReport(recommendations=recs, evidence_by_id=evidence_by_id)
