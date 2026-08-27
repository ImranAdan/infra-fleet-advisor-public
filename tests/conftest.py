import subprocess
from pathlib import Path

import pytest

from infra_fleet_advisor.runtime.clock import FixedClock

FIXTURES = Path(__file__).parent / "fixtures"


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)  # noqa: S603


@pytest.fixture
def git_checkout(tmp_path: Path):
    """Build a real, clean tmp-path git repo and return a factory that
    populates .github/workflows/ from named fixture files, commits, and
    returns (checkout_path, sha)."""

    counter = iter(range(10_000))

    def _make(
        *workflow_fixture_names: str, terraform_files: tuple[str, ...] = ()
    ) -> tuple[Path, str]:
        repo = tmp_path / f"checkout-{next(counter)}"
        repo.mkdir(parents=True)
        _run("git", "init", "-q", cwd=repo)
        _run("git", "config", "user.email", "test@example.com", cwd=repo)
        _run("git", "config", "user.name", "Test", cwd=repo)

        (repo / "README.md").write_text("fixture repo\n", encoding="utf-8")

        workflows_dir = repo / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        for name in workflow_fixture_names:
            (workflows_dir / name).write_text(
                (FIXTURES / "workflows" / name).read_text(encoding="utf-8"), encoding="utf-8"
            )

        if terraform_files:
            tf_dir = repo / "infrastructure" / "permanent"
            tf_dir.mkdir(parents=True)
            for name in terraform_files:
                (tf_dir / name).write_text(
                    (FIXTURES / "terraform" / name).read_text(encoding="utf-8"), encoding="utf-8"
                )

        _run("git", "add", "-A", cwd=repo)
        _run("git", "commit", "-q", "-m", "fixture commit", cwd=repo)
        sha = subprocess.run(  # fixed argv, test-only fixture helper
            ["git", "rev-parse", "HEAD"],  # noqa: S603,S607
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return repo, sha

    return _make


@pytest.fixture
def fixed_clock() -> FixedClock:
    return FixedClock("2026-08-26T00:00:00+00:00")
