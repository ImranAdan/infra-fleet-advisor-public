from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    dependency_update_collector as collector,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)

DEPENDABOT = """version: 2
updates:
  - package-ecosystem: pip
    directory: /app
    schedule: {interval: monthly}
  - package-ecosystem: github-actions
    directory: /
    schedule: {interval: monthly}
  - package-ecosystem: terraform
    directories: ["/infra/*"]
    schedule: {interval: weekly}
"""


def _coverage(tmp_path: Path, files: dict[str, str]) -> dict[str, bool]:
    for rel_path, text in files.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    result = collector.collect(tmp_path, LIMITS, tracked_paths=frozenset(files))
    assert result.coverage.status == "ok"
    return {item.locator: bool(item.fact["covered_by_dependabot"]) for item in result.evidence}


def test_each_manifest_directory_is_matched_to_an_update_entry(tmp_path: Path) -> None:
    coverage = _coverage(
        tmp_path,
        {
            ".github/dependabot.yml": DEPENDABOT,
            ".github/workflows/ci.yml": "on: push\n",
            "app/requirements.txt": "flask==3.0\n",
            "app/Dockerfile": "FROM python:3.12\n",
            "requirements-dev.txt": "gitlint==0.19.1\n",
            "infra/staging/main.tf": "terraform {\n  required_providers {}\n}\n",
            "infra/staging/modules/role/main.tf": 'resource "x" "y" {}\n',
        },
    )

    assert coverage == {
        "github-actions:/": True,
        "pip:app": True,
        "docker:app": False,
        "pip:/": False,
        "terraform:infra/staging": True,
    }


def test_missing_configuration_leaves_every_manifest_uncovered(tmp_path: Path) -> None:
    coverage = _coverage(tmp_path, {"svc/Dockerfile": "FROM alpine\n"})

    assert coverage == {"docker:svc": False}


def test_malformed_configuration_is_partial(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "dependabot.yml").write_text("updates: nope\n", encoding="utf-8")

    result = collector.collect(
        tmp_path, LIMITS, tracked_paths=frozenset({".github/dependabot.yml"})
    )

    assert result.coverage.status == "partial"
    assert result.evidence == ()


def test_untracked_manifests_are_not_evidence(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")

    result = collector.collect(tmp_path, LIMITS, tracked_paths=frozenset())

    assert result.evidence == ()
