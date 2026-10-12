from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.agent_rules_collector import (  # noqa: E501
    collect,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=1024 * 1024,
    max_recommendations=10,
    max_manifest_files=100,
    max_manifest_file_bytes=1024 * 1024,
)
AGENTS = "# Agent guidelines\n\n## Autonomy\n\n**Owner-only actions.** Never...\n"
TEMPLATE = "<!-- autonomous-merge -->\n\n## Verification\n"
PATHS = frozenset({"AGENTS.md", ".github/pull_request_template.md"})


def _fleet(tmp_path: Path, agents: str, template: str) -> Path:
    (tmp_path / ".github").mkdir()
    (tmp_path / "AGENTS.md").write_text(agents)
    (tmp_path / ".github" / "pull_request_template.md").write_text(template)
    return tmp_path


def test_declared_rules_yield_one_present_record_per_file(tmp_path: Path) -> None:
    result = collect(_fleet(tmp_path, AGENTS, TEMPLATE), LIMITS, frozenset(), PATHS)

    assert result.coverage.status == "ok"
    assert {e.source_path: e.fact for e in result.evidence} == {
        "AGENTS.md": {"rules_present": True, "missing_markers": 0},
        ".github/pull_request_template.md": {"rules_present": True, "missing_markers": 0},
    }


def test_removed_marker_or_section_is_reported_missing(tmp_path: Path) -> None:
    agents = AGENTS.replace("## Autonomy", "## Asking first")
    template = TEMPLATE.replace("<!-- autonomous-merge -->", "<!-- held -->")
    result = collect(_fleet(tmp_path, agents, template), LIMITS, frozenset(), PATHS)

    assert {e.source_path: e.fact for e in result.evidence} == {
        "AGENTS.md": {"rules_present": False, "missing_markers": 1},
        ".github/pull_request_template.md": {"rules_present": False, "missing_markers": 1},
    }
    assert [e.excerpt for e in result.evidence if e.source_path == "AGENTS.md"] == [
        "AGENTS.md: missing ## Autonomy"
    ]


def test_untracked_or_excluded_files_yield_no_record(tmp_path: Path) -> None:
    fleet = _fleet(tmp_path, AGENTS, TEMPLATE)

    assert collect(fleet, LIMITS, frozenset(), frozenset()).evidence == ()
    excluded = collect(fleet, LIMITS, frozenset({".github"}), PATHS)
    assert [e.source_path for e in excluded.evidence] == ["AGENTS.md"]


def test_unreadable_rule_file_makes_coverage_partial(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text(AGENTS)
    (tmp_path / "AGENTS.md").symlink_to(tmp_path / "real.md")

    result = collect(tmp_path, LIMITS, frozenset(), frozenset({"AGENTS.md"}))

    assert result.coverage.status == "partial"
    assert result.evidence == ()
