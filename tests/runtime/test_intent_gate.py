import json
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.cli import EXIT_INTENT_REGRESSION, EXIT_OK, main
from infra_fleet_advisor.runtime.intent_gate import compare_reports, to_markdown


def _report(
    path: Path,
    statuses: dict[str, str],
    *,
    digest: str = "intent-md-v1:x",
    coverage: str = "ok",
) -> Path:
    evaluations = [
        {
            "document_id": "cost",
            "proposition_id": key,
            "status": status,
            "statement": f"Position {key}\nsecond line",
            "evidence_ids": [f"c:{key}"] if status == "divergent" else [],
        }
        for key, status in statuses.items()
    ]
    evidence = [
        {"evidence_id": f"c:{key}", "source_path": "eks.tf", "excerpt": f"<b>{key}</b> @ops"}
        for key, status in statuses.items()
        if status == "divergent"
    ]
    path.write_text(
        json.dumps(
            {
                "provenance": {"intent_digest": digest},
                "coverage": [{"collector_id": "cost", "status": coverage}],
                "intent_evaluations": evaluations,
                "evidence": evidence,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_gate_separates_new_resolved_and_persisting_divergences(tmp_path: Path) -> None:
    base = _report(
        tmp_path / "base.json",
        {"C-001": "divergent", "C-002": "divergent", "C-003": "satisfied"},
    )
    head = _report(
        tmp_path / "head.json",
        {"C-001": "divergent", "C-002": "satisfied", "C-003": "divergent"},
        coverage="partial",
    )

    result = compare_reports(base, head)

    assert [p.key for p in result.regressions] == ["cost/C-003"]
    assert [p.key for p in result.resolutions] == ["cost/C-002"]
    assert [p.key for p in result.persisting] == ["cost/C-001"]
    assert result.degraded_collectors == ("cost",)
    assert not result.passed
    markdown = to_markdown(result)
    assert "fails: 1 declared position(s)" in markdown
    assert "Position C-003" in markdown and "second line" not in markdown
    # Fleet-derived evidence is inert text in the job summary.
    assert "<b>" not in markdown and "&#64;ops" in markdown


def test_gate_passes_when_nothing_newly_diverges(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", {"C-001": "divergent"})
    head = _report(tmp_path / "head.json", {"C-001": "declared_unverified"})

    assert compare_reports(base, head).passed


def test_gate_refuses_reports_from_different_catalogs(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", {}, digest="intent-md-v1:a")
    head = _report(tmp_path / "head.json", {}, digest="intent-md-v1:b")

    with pytest.raises(PolicyError, match="same intent catalog"):
        compare_reports(base, head)


def test_gate_cli_exit_code_is_the_verdict(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", {"C-001": "satisfied"})
    bad = _report(tmp_path / "bad.json", {"C-001": "divergent"})
    summary = tmp_path / "summary.md"

    assert main(["gate", "--base-report", str(base), "--head-report", str(base)]) == EXIT_OK
    assert (
        main(
            [
                "gate",
                "--base-report",
                str(base),
                "--head-report",
                str(bad),
                "--summary",
                str(summary),
            ]
        )
        == EXIT_INTENT_REGRESSION
    )
    assert "Newly divergent" in summary.read_text(encoding="utf-8")
