import json
import subprocess
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.drill import (
    Drill,
    drills_passed,
    load_drills,
    run_drills,
    to_markdown,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed test argv
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _fake_review(worktree: Path, _sha: str, output: Path) -> None:
    """A stand-in review: C-001 diverges when retention exceeds 30 days."""
    text = (worktree / "eks.tf").read_text(encoding="utf-8")
    statuses = {
        "C-001": "divergent" if "retention = 90" in text else "satisfied",
        "C-002": "declared_unverified",
        "C-009": "divergent",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(
            {
                "intent_evaluations": [
                    {"proposition_id": key, "status": value} for key, value in statuses.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def test_drills_report_caught_missed_stale_and_already_divergent(tmp_path: Path) -> None:
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    _git(fleet, "init", "-q")
    (fleet / "eks.tf").write_text("retention = 14\nmax = 2\n", encoding="utf-8")
    _git(fleet, "add", "-A")
    _git(fleet, "commit", "-qm", "base")
    drills = (
        Drill("C-001", "eks.tf", "retention = 14", "retention = 90"),
        Drill("C-002", "eks.tf", "max = 2", "max = 1"),
        Drill("C-003", "eks.tf", "no such text", "x"),
        Drill("C-009", "eks.tf", "max = 2", "max = 3"),
    )

    results = run_drills(fleet, drills, _fake_review, tmp_path / "out")

    assert [r.outcome for r in results] == ["caught", "missed", "stale", "already_divergent"]
    assert not drills_passed(results)
    assert "**MISSED**" in to_markdown(results)
    # The fleet checkout is untouched and its worktree removed.
    assert (fleet / "eks.tf").read_text(encoding="utf-8") == "retention = 14\nmax = 2\n"
    worktrees = subprocess.run(  # noqa: S603
        ["git", "worktree", "list"],  # noqa: S607
        cwd=fleet,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert len(worktrees.splitlines()) == 1


def test_drill_file_rejects_unknown_fields_and_unsafe_paths(tmp_path: Path) -> None:
    path = tmp_path / "drills.yaml"
    for body in (
        "drills:\n  - {proposition: C-1, path: a, find: b, replace: c, run: rm}\n",
        "drills:\n  - {proposition: C-1, path: ../a, find: b, replace: c}\n",
        "drills: []\n",
    ):
        path.write_text(body, encoding="utf-8")
        with pytest.raises(PolicyError):
            load_drills(path)


def test_production_drills_name_registered_propositions() -> None:
    drills = load_drills(Path(__file__).parents[2] / "drills" / "fleet-mutations.yaml")

    assert len({(drill.proposition, drill.path) for drill in drills}) == len(drills)


def test_symlinked_drill_target_is_stale_and_never_written(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("retention = 14\n", encoding="utf-8")
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    _git(fleet, "init", "-q")
    (fleet / "eks.tf").write_text("retention = 14\n", encoding="utf-8")
    (fleet / "link.tf").symlink_to(outside)
    _git(fleet, "add", "-A")
    _git(fleet, "commit", "-qm", "base")

    [result] = run_drills(
        fleet,
        (Drill("C-001", "link.tf", "retention = 14", "retention = 90"),),
        _fake_review,
        tmp_path / "out",
    )

    assert result.outcome == "stale"
    assert outside.read_text(encoding="utf-8") == "retention = 14\n"


def test_drill_cli_refuses_output_inside_the_fleet(tmp_path: Path) -> None:
    from infra_fleet_advisor.runtime.cli import EXIT_UNSAFE_OUTPUT_ERROR, main

    fleet = tmp_path / "fleet"
    fleet.mkdir()
    code = main(
        [
            "drill",
            "--checkout",
            str(fleet),
            "--drills",
            "unused.yaml",
            "--policy",
            "policy.yaml",
            "--intent-dir",
            "intent",
            "--output-dir",
            str(fleet / "out"),
        ]
    )

    assert code == EXIT_UNSAFE_OUTPUT_ERROR
    assert not (fleet / "out").exists()


def test_undecodable_drill_target_is_stale(tmp_path: Path) -> None:
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    _git(fleet, "init", "-q")
    (fleet / "eks.tf").write_text("retention = 14\n", encoding="utf-8")
    (fleet / "binary.tf").write_bytes(b"\xff\xfe\x00retention")
    _git(fleet, "add", "-A")
    _git(fleet, "commit", "-qm", "base")

    [result] = run_drills(
        fleet, (Drill("C-001", "binary.tf", "retention", "x"),), _fake_review, tmp_path / "out"
    )

    assert result.outcome == "stale"
