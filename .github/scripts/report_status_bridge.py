#!/usr/bin/env python3
"""Relay an exact-head report Quality run into PR-associated required statuses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

REPORT_BRANCH = "advisory/latest"
REPORT_AUTHOR = "github-actions[bot]"
REPORT_FILES = {"reports/report.json", "reports/report.md"}
EVIDENCE_JOBS = {
    "Conventional commits",
    "Lint, types, and unit tests",
    "Check drills",
    "Ratchet guard (dispatched)",
    "Workflow lint",
    "Trivy security scan",
}
REQUIRED_CONTEXTS = {
    "Conventional commits",
    "Lint, types, and unit tests",
    "Workflow lint",
    "Trivy security scan",
}
API_TIMEOUT_SECONDS = 30


def validate(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    repository: str,
    number: int,
    head: str,
) -> None:
    """Fail closed unless trusted report metadata and every evidence job agree."""
    head_data = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    head_repo = head_data.get("repo") if isinstance(head_data.get("repo"), dict) else {}
    base_data = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    author = pr.get("user") if isinstance(pr.get("user"), dict) else {}
    if not (
        pr.get("number") == number
        and pr.get("state") == "open"
        and author.get("login") == REPORT_AUTHOR
        and head_data.get("ref") == REPORT_BRANCH
        and head_data.get("sha") == head
        and head_repo.get("full_name") == repository
        and base_data.get("ref") == "main"
    ):
        raise ValueError("pull request is not the expected open bot-authored report head")

    changed = {item.get("filename") for item in files if isinstance(item, dict)}
    if changed != REPORT_FILES or len(files) != len(REPORT_FILES):
        raise ValueError("report pull request does not contain exactly the two report files")

    run_repository = run.get("repository") if isinstance(run.get("repository"), dict) else {}
    if not (
        run.get("name") == "Quality"
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == REPORT_BRANCH
        and run.get("head_sha") == head
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run_repository.get("full_name") == repository
    ):
        raise ValueError("Quality run is not a successful exact-head report dispatch")

    conclusions: dict[str, list[str | None]] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise ValueError("Quality returned malformed job metadata")
        conclusions.setdefault(job["name"], []).append(job.get("conclusion"))
    for name in EVIDENCE_JOBS:
        if conclusions.get(name) != ["success"]:
            raise ValueError(f"Quality evidence job did not pass exactly once: {name}")


def skip_reason(pr: dict[str, Any]) -> str | None:
    """Why a report PR needs no statuses: it closed while Quality ran.

    Publishing nothing is always safe, so a merged or declined report is a
    no-op rather than a failure; validate() still gates every open PR.
    """
    if pr.get("state") != "closed":
        return None
    return "merged" if pr.get("merged") else "closed without merging"


def status_payloads(run_url: str) -> list[dict[str, str]]:
    """Build the branch-protection contexts backed by the audited Quality run."""
    return [
        {
            "state": "success",
            "context": context,
            "description": "Passed in the exact-head report Quality run",
            "target_url": run_url,
        }
        for context in sorted(REQUIRED_CONTEXTS)
    ]


def _gh_json(arguments: list[str], payload: dict[str, str] | None = None) -> Any:
    command = ["/usr/bin/env", "gh", "api", *arguments]
    result = subprocess.run(  # noqa: S603 - fixed executable and validated API arguments
        command,
        input=json.dumps(payload) if payload is not None else None,
        check=True,
        capture_output=True,
        text=True,
        timeout=API_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def _self_test() -> int:
    repository = "owner/advisor"
    head = "a" * 40
    pr = {
        "number": 7,
        "state": "open",
        "user": {"login": REPORT_AUTHOR},
        "head": {"ref": REPORT_BRANCH, "sha": head, "repo": {"full_name": repository}},
        "base": {"ref": "main"},
    }
    files = [{"filename": name} for name in sorted(REPORT_FILES)]
    run = {
        "name": "Quality",
        "event": "workflow_dispatch",
        "head_branch": REPORT_BRANCH,
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://example.invalid/run/9",
        "repository": {"full_name": repository},
    }
    jobs = [{"name": name, "conclusion": "success"} for name in sorted(EVIDENCE_JOBS)]
    validate(pr, files, run, jobs, repository, 7, head)
    assert {item["context"] for item in status_payloads(run["html_url"])} == REQUIRED_CONTEXTS

    invalid_cases = (
        ({**pr, "user": {"login": "attacker"}}, files, run, jobs),
        (pr, files + [{"filename": "src/changed.py"}], run, jobs),
        (pr, files, {**run, "head_sha": "b" * 40}, jobs),
        (pr, files, run, [{**jobs[0], "conclusion": "failure"}, *jobs[1:]]),
    )
    for candidate_pr, candidate_files, candidate_run, candidate_jobs in invalid_cases:
        try:
            validate(
                candidate_pr,
                candidate_files,
                candidate_run,
                candidate_jobs,
                repository,
                7,
                head,
            )
        except ValueError:
            continue
        raise AssertionError("status bridge accepted invalid evidence")
    assert skip_reason(pr) is None
    assert skip_reason({**pr, "state": "closed", "merged": True}) == "merged"
    assert skip_reason({**pr, "state": "closed", "merged": False}) == "closed without merging"
    print("self-test passed")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return _self_test()
    if len(sys.argv) != 4:
        print("usage: report_status_bridge.py PR_NUMBER HEAD_SHA QUALITY_RUN_ID", file=sys.stderr)
        return 2
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if repository.count("/") != 1:
        print("GITHUB_REPOSITORY must be owner/name", file=sys.stderr)
        return 2
    try:
        number = int(sys.argv[1])
        run_id = int(sys.argv[3])
    except ValueError:
        print("PR_NUMBER and QUALITY_RUN_ID must be integers", file=sys.stderr)
        return 2
    head = sys.argv[2]
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        print("HEAD_SHA must be a lowercase 40-character hexadecimal commit", file=sys.stderr)
        return 2

    try:
        pr = _gh_json([f"repos/{repository}/pulls/{number}"])
        if isinstance(pr, dict) and (reason := skip_reason(pr)):
            print(f"report PR #{number} was {reason} before its statuses; nothing to publish")
            return 0
        files = _gh_json([f"repos/{repository}/pulls/{number}/files?per_page=100"])
        run = _gh_json([f"repos/{repository}/actions/runs/{run_id}"])
        jobs_document = _gh_json(
            [f"repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"]
        )
        if not isinstance(pr, dict) or not isinstance(files, list) or not isinstance(run, dict):
            raise ValueError("GitHub returned malformed report evidence")
        if not isinstance(jobs_document, dict) or not isinstance(jobs_document.get("jobs"), list):
            raise ValueError("GitHub returned malformed Quality jobs")
        validate(pr, files, run, jobs_document["jobs"], repository, number, head)
        run_url = run.get("html_url")
        if not isinstance(run_url, str) or not run_url.startswith("https://github.com/"):
            raise ValueError("Quality run has no trusted GitHub audit URL")
        for payload in status_payloads(run_url):
            _gh_json(
                ["--method", "POST", f"repos/{repository}/statuses/{head}", "--input", "-"],
                payload,
            )
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"report status bridge refused evidence: {error}", file=sys.stderr)
        return 1
    print(f"published {len(REQUIRED_CONTEXTS)} required statuses for report PR #{number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
