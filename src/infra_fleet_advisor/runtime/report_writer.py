import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import MAX_EXCERPT_LENGTH, Evidence
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.report import Report

MAX_PRIOR_REPORT_BYTES = 2 * 1024 * 1024


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
    )


def _parse_prior_evidence(e: dict[str, Any]) -> Evidence:
    fact = e.get("fact")
    return Evidence(
        evidence_id=_require_str(e["evidence_id"], "evidence_id"),
        kind=_require_str(e["kind"], "kind"),
        source_path=_require_str(e["source_path"], "source_path"),
        locator=_require_str(e["locator"], "locator"),
        excerpt=_require_str(e["excerpt"], "excerpt")[:MAX_EXCERPT_LENGTH],
        fact=fact if isinstance(fact, dict) else {},
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
    return "\n".join(lines)


def write_report(report: Report, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


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
        evidence_by_id = {
            ev.evidence_id: ev for ev in (_parse_prior_evidence(e) for e in raw.get("evidence", []))
        }
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        raise PolicyError(f"malformed prior report: {exc}") from exc
    return PriorReport(recommendations=recs, evidence_by_id=evidence_by_id)
