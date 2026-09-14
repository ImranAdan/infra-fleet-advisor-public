import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/check-approved-report-current.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _publication_checkout(git_checkout, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    author, _ = git_checkout()
    _git(author, "branch", "-M", "main")
    (author / "reports").mkdir()
    (author / "reports/report.json").write_text('{"version":1}\n')
    (author / "policy.yaml").write_text("version: '1.0'\n")
    (author / "intent").mkdir()
    (author / "intent/example.md").write_text("Declared intent\n")
    _git(author, "add", "-A")
    _git(author, "commit", "-qm", "chore: approve fixture report")
    remote = tmp_path / "remote.git"
    _git(author, "clone", "--bare", str(author), str(remote))
    _git(author, "remote", "add", "origin", str(remote))
    worker = tmp_path / "publisher"
    _git(author, "clone", "--no-local", str(remote), str(worker))
    runner = tmp_path / "runner"
    runner.mkdir()
    approved = runner / "approved-report.json"
    approved.write_bytes((author / "reports/report.json").read_bytes())
    return author, worker, runner, approved


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (None, "true"),
        ("README.md", "true"),
        ("reports/report.json", "false"),
        ("policy.yaml", "false"),
        ("intent/example.md", "false"),
        ("src/infra_fleet_advisor/core/validation.py", "false"),
        (".github/workflows/fleet-issues.yml", "false"),
        ("uv.lock", "false"),
    ],
)
def test_publication_rechecks_main_after_the_initial_checkout(
    git_checkout, tmp_path: Path, change: str | None, expected: str
) -> None:
    author, worker, runner, approved = _publication_checkout(git_checkout, tmp_path)
    if change is not None:
        path = author / change
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Superseding merged state\n")
        _git(author, "add", "-A")
        _git(author, "commit", "-qm", "fix: supersede fixture state")
        _git(author, "push", "origin", "main")

    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), str(approved)],  # noqa: S607
        cwd=worker,
        env={**os.environ, "RUNNER_TEMP": str(runner)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == expected


def test_failed_freshness_read_cannot_authorize_issue_writes(git_checkout, tmp_path: Path) -> None:
    _, worker, runner, approved = _publication_checkout(git_checkout, tmp_path)
    _git(worker, "remote", "remove", "origin")
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), str(approved)],  # noqa: S607
        cwd=worker,
        env={**os.environ, "RUNNER_TEMP": str(runner)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.stdout.strip() != "true"
