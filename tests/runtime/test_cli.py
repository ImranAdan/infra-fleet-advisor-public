import json
from pathlib import Path

from infra_fleet_advisor.runtime.cli import (
    EXIT_OK,
    EXIT_PROVENANCE_ERROR,
    EXIT_UNSAFE_OUTPUT_ERROR,
    main,
)

POLICY = Path(__file__).parent.parent / "fixtures" / "policies" / "valid_policy.yaml"


def _argv(repo: Path, sha: str, output_dir: Path, prior: Path | None = None) -> list[str]:
    argv = [
        "review",
        "--checkout",
        str(repo),
        "--sha",
        sha,
        "--policy",
        str(POLICY),
        "--output-dir",
        str(output_dir),
        # Keeps the suite hermetic: the CLI now defaults to the real model.
        "--synthesizer",
        "stub",
    ]
    if prior is not None:
        argv += ["--prior-report", str(prior)]
    return argv


def test_full_run_produces_schema_valid_reports_without_cloud_creds(
    git_checkout, tmp_path: Path
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"

    exit_code = main(_argv(repo, sha, output_dir))

    assert exit_code == EXIT_OK
    payload = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["new_count"] == 1
    assert (output_dir / "report.md").exists()


def test_sha_mismatch_exits_with_provenance_error(git_checkout, tmp_path: Path) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    exit_code = main(_argv(repo, "0" * 40, tmp_path / "out"))
    assert exit_code == EXIT_PROVENANCE_ERROR


def test_output_dir_inside_checkout_is_rejected(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    exit_code = main(_argv(repo, sha, repo / "review-output"))
    assert exit_code == EXIT_UNSAFE_OUTPUT_ERROR
    assert not (repo / "review-output").exists()


def test_second_run_reports_lifecycle_changes(git_checkout, tmp_path: Path) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    first_out = tmp_path / "first"
    main(_argv(repo, sha, first_out))

    second_out = tmp_path / "second"
    exit_code = main(_argv(repo, sha, second_out, prior=first_out / "report.json"))

    assert exit_code == EXIT_OK
    payload = json.loads((second_out / "report.json").read_text(encoding="utf-8"))
    assert payload["unchanged_count"] == 1
    assert payload["new_count"] == 0
