from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.documentation_link_collector import (  # noqa: E501
    broken_links,
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
KNOWN = frozenset({"README.md", "docs", "docs/GUIDE.md", "scripts", "scripts/run.sh", "."})


def test_relative_links_resolve_from_the_linking_file() -> None:
    text = (
        "[guide](docs/GUIDE.md) [run](scripts/run.sh#L3) [dir](docs/) [top](#intro) "
        '[web](https://example.com) [mail](mailto:a@b.c) [site](/abs) [titled](docs/GUIDE.md "t")'
    )
    assert broken_links("README.md", text, KNOWN) == []
    assert broken_links("docs/GUIDE.md", "[back](../README.md)", KNOWN) == []


def test_missing_targets_and_escapes_are_broken() -> None:
    text = "[gone](docs/OLD.md) [up](../../etc/passwd) [ok](docs/GUIDE.md)"
    assert broken_links("README.md", text, KNOWN) == ["docs/OLD.md", "../../etc/passwd"]


def test_links_in_fenced_code_are_ignored() -> None:
    text = "```markdown\n[example](not/a/file.md)\n```\n~~~\n[x](nope.md)\n~~~\n"
    assert broken_links("README.md", text, KNOWN) == []


def test_collect_emits_one_record_per_markdown_file(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("[guide](docs/GUIDE.md) [gone](docs/OLD.md)\n")
    (tmp_path / "docs" / "GUIDE.md").write_text("[back](../README.md)\n")
    (tmp_path / "notes.txt").write_text("[ignored](missing.md)\n")

    result = collect(
        tmp_path,
        LIMITS,
        excluded_paths=frozenset(),
        tracked_paths=frozenset({"README.md", "docs/GUIDE.md", "notes.txt"}),
    )

    assert result.coverage.status == "ok"
    facts = {e.source_path: e.fact for e in result.evidence}
    assert facts == {
        "README.md": {"links_resolve": False, "broken_links": 1},
        "docs/GUIDE.md": {"links_resolve": True, "broken_links": 0},
    }


def test_unreadable_markdown_makes_coverage_partial(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text("ok\n")
    (tmp_path / "link.md").symlink_to(tmp_path / "real.md")

    result = collect(
        tmp_path,
        LIMITS,
        excluded_paths=frozenset(),
        tracked_paths=frozenset({"real.md", "link.md"}),
    )

    assert result.coverage.status == "partial"
