import json
from dataclasses import asdict
from pathlib import Path

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.lifecycle import PriorRecommendation, PriorReport
from infra_fleet_advisor.core.report import Report

MAX_PRIOR_REPORT_BYTES = 2 * 1024 * 1024


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
    if path.stat().st_size > MAX_PRIOR_REPORT_BYTES:
        raise PolicyError(f"prior report exceeds {MAX_PRIOR_REPORT_BYTES} bytes")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        recs = [
            PriorRecommendation(
                fingerprint=r["fingerprint"],
                concern_key=r["concern_key"],
                category=r["category"],
                priority=r["priority"],
                title=r["title"],
                summary=r["summary"],
                evidence_ids=tuple(r["evidence_ids"]),
                impact=r["impact"],
                suggested_change=r["suggested_change"],
                trade_offs=r["trade_offs"],
                confidence=r["confidence"],
                confidence_explanation=r["confidence_explanation"],
            )
            for r in raw["recommendations"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PolicyError(f"malformed prior report: {exc}") from exc
    return PriorReport(recommendations=recs)
