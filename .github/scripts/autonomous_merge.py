#!/usr/bin/env python3
"""Merge same-repository pull requests that opt into the evidence gate."""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MARKER = "<!-- autonomous-merge -->"
GATE = Path(".claude/skills/merge-gate/merge_ready.py")
DEFERRED = {1, 10, 11}
LIST_TIMEOUT_SECONDS = 60
GATE_TIMEOUT_SECONDS = 120
HANDOFF_TIMEOUT_SECONDS = 60
WORKER_BUDGET_SECONDS = 480
SHUTDOWN_RESERVE_SECONDS = 30
MAX_CANDIDATES_PER_RUN = 20


def eligible(pr: dict[str, Any], repository: str, now: datetime, minimum_age: int) -> bool:
    """Accept only mature, non-draft PRs from a branch in this repository."""
    owner, name = repository.split("/", 1)
    head_owner = (pr.get("headRepositoryOwner") or {}).get("login")
    head_name = (pr.get("headRepository") or {}).get("name")
    body = pr.get("body") or ""
    try:
        created = datetime.fromisoformat(str(pr["createdAt"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return False
    if created.tzinfo is None:
        return False
    age = (now - created).total_seconds()
    return (
        not pr.get("isDraft", False)
        and head_owner == owner
        and head_name == name
        and MARKER in body
        and age >= minimum_age
    )


def post_merge_command(pr: dict[str, Any], repository: str) -> list[str] | None:
    """Build the trusted optional handoff for one known generated branch."""
    workflow = os.environ.get("AUTONOMOUS_MERGE_POST_MERGE_WORKFLOW", "")
    head = os.environ.get("AUTONOMOUS_MERGE_POST_MERGE_HEAD", "")
    if not workflow or not head or pr.get("headRefName") != head:
        return None
    return [
        "gh",
        "workflow",
        "run",
        workflow,
        "--repo",
        repository,
        "-f",
        f"report_pr={pr['number']}",
    ]


def ordered_candidates(candidates: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Return a bounded hourly window so a slow prefix cannot starve later PRs."""
    ordered = sorted(candidates, key=lambda item: int(item["number"]))
    if not ordered:
        return []
    window = min(MAX_CANDIDATES_PER_RUN, len(ordered))
    hour = int(now.timestamp() // 3600)
    start = (hour * window) % len(ordered)
    rotated = ordered[start:] + ordered[:start]
    return rotated[:window]


def shared_timeout(remaining_seconds: float, remaining_operations: int, maximum: int) -> int:
    """Share the run budget between remaining operations and preserve shutdown time."""
    if remaining_operations < 1:
        return 0
    distributable = remaining_seconds - SHUTDOWN_RESERVE_SECONDS
    if distributable < 1:
        return 0
    return min(maximum, max(1, int(distributable / remaining_operations)))


def _self_test() -> int:
    now = datetime(2026, 9, 28, 12, tzinfo=UTC)
    candidate = {
        "number": 7,
        "body": f"Verification\n{MARKER}",
        "createdAt": "2026-09-28T11:30:00Z",
        "isDraft": False,
        "headRepositoryOwner": {"login": "owner"},
        "headRepository": {"name": "repo"},
    }
    assert eligible(candidate, "owner/repo", now, 900)
    assert not eligible({**candidate, "isDraft": True}, "owner/repo", now, 900)
    assert not eligible({**candidate, "body": "ordinary PR"}, "owner/repo", now, 900)
    assert not eligible(
        {**candidate, "headRepositoryOwner": {"login": "fork"}}, "owner/repo", now, 900
    )
    assert not eligible({**candidate, "createdAt": "2026-09-28T11:50:00Z"}, "owner/repo", now, 900)
    assert not eligible({**candidate, "createdAt": "invalid"}, "owner/repo", now, 900)
    assert not eligible({**candidate, "createdAt": "2026-09-28T11:30:00"}, "owner/repo", now, 900)
    os.environ["AUTONOMOUS_MERGE_POST_MERGE_WORKFLOW"] = "publish.yml"
    os.environ["AUTONOMOUS_MERGE_POST_MERGE_HEAD"] = "advisory/latest"
    assert post_merge_command({**candidate, "headRefName": "advisory/latest"}, "owner/repo") == [
        "gh",
        "workflow",
        "run",
        "publish.yml",
        "--repo",
        "owner/repo",
        "-f",
        "report_pr=7",
    ]
    assert post_merge_command({**candidate, "headRefName": "feature"}, "owner/repo") is None
    candidates = [{**candidate, "number": number} for number in range(1, 26)]
    first_window = ordered_candidates(candidates, now)
    next_window = ordered_candidates(candidates, now.replace(hour=13))
    assert len(first_window) == MAX_CANDIDATES_PER_RUN
    assert {item["number"] for item in first_window} != {item["number"] for item in next_window}
    assert {item["number"] for item in first_window + next_window} == set(range(1, 26))
    assert shared_timeout(480, 4, GATE_TIMEOUT_SECONDS) == 112
    assert shared_timeout(480, 1, GATE_TIMEOUT_SECONDS) == GATE_TIMEOUT_SECONDS
    assert shared_timeout(SHUTDOWN_RESERVE_SECONDS, 1, GATE_TIMEOUT_SECONDS) == 0
    pages = json.dumps(
        [
            [
                {
                    "number": 7,
                    "body": f"Verification\n{MARKER}",
                    "created_at": "2026-09-28T11:30:00Z",
                    "draft": False,
                    "head": {
                        "ref": "feature",
                        "repo": {"name": "repo", "owner": {"login": "owner"}},
                    },
                }
            ],
            [],
        ]
    )
    assert _parse_pull_request_pages(pages) == [
        {
            **candidate,
            "headRefName": "feature",
        }
    ]
    del os.environ["AUTONOMOUS_MERGE_POST_MERGE_WORKFLOW"]
    del os.environ["AUTONOMOUS_MERGE_POST_MERGE_HEAD"]
    print("self-test passed")
    return 0


def _open_pull_requests(repository: str) -> list[dict[str, Any]]:
    result = subprocess.run(  # noqa: S603 - fixed gh argv, validated repository
        [
            "/usr/bin/env",
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/pulls?state=open&per_page=100",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=LIST_TIMEOUT_SECONDS,
    )
    return _parse_pull_request_pages(result.stdout)


def _parse_pull_request_pages(raw: str) -> list[dict[str, Any]]:
    """Normalize every REST page into the fields used by the eligibility gate."""
    pages = json.loads(raw)
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ValueError("GitHub returned malformed pull-request pages")
    normalized = []
    for page in pages:
        for item in page:
            if not isinstance(item, dict) or not isinstance(item.get("number"), int):
                raise ValueError("GitHub returned a malformed pull request")
            head = item.get("head") if isinstance(item.get("head"), dict) else {}
            repository = head.get("repo") if isinstance(head.get("repo"), dict) else {}
            owner = repository.get("owner") if isinstance(repository.get("owner"), dict) else {}
            normalized.append(
                {
                    "number": item["number"],
                    "body": item.get("body"),
                    "createdAt": item.get("created_at"),
                    "isDraft": item.get("draft", False),
                    "headRefName": head.get("ref"),
                    "headRepository": {"name": repository.get("name")},
                    "headRepositoryOwner": {"login": owner.get("login")},
                }
            )
    return normalized


def _summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return _self_test()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if repository.count("/") != 1:
        print("GITHUB_REPOSITORY must be owner/name", file=sys.stderr)
        return 2
    try:
        minimum_age = int(os.environ.get("AUTONOMOUS_MERGE_MIN_AGE_SECONDS", "900"))
    except ValueError:
        print("AUTONOMOUS_MERGE_MIN_AGE_SECONDS must be an integer", file=sys.stderr)
        return 2
    if minimum_age < 0:
        print("AUTONOMOUS_MERGE_MIN_AGE_SECONDS cannot be negative", file=sys.stderr)
        return 2

    lines = ["## Autonomous merge", ""]
    try:
        open_pull_requests = _open_pull_requests(repository)
    except subprocess.TimeoutExpired:
        message = f"Pull-request discovery timed out after {LIST_TIMEOUT_SECONDS} seconds."
        lines.append(message)
        _summary(lines)
        print(message, file=sys.stderr)
        return 1
    now = datetime.now(UTC)
    eligible_candidates = [
        pr for pr in open_pull_requests if eligible(pr, repository, now, minimum_age)
    ]
    candidates = ordered_candidates(eligible_candidates, now)
    deadline = time.monotonic() + WORKER_BUDGET_SECONDS
    unexpected = False
    if not candidates:
        lines.append("No eligible pull request is ready for evaluation.")
    elif len(candidates) < len(eligible_candidates):
        lines.append(
            f"Evaluating {len(candidates)} of {len(eligible_candidates)} eligible pull requests "
            "in this hour's rotating window."
        )
        lines.append("")
    for index, pr in enumerate(candidates):
        number = str(pr["number"])
        remaining = candidates[index:]
        remaining_operations = len(remaining) + sum(
            post_merge_command(candidate, repository) is not None for candidate in remaining
        )
        gate_timeout = shared_timeout(
            deadline - time.monotonic(), remaining_operations, GATE_TIMEOUT_SECONDS
        )
        if gate_timeout == 0:
            output = "Shared execution budget is exhausted; retrying in the next hourly window."
            state = "deferred"
            result = None
            lines.extend(
                [
                    f"### PR #{number}: {state}",
                    "",
                    f"<pre>{html.escape(output)}</pre>",
                    "",
                ]
            )
            print(f"PR #{number}: {state}\n{output}")
            continue
        try:
            result = subprocess.run(  # noqa: S603 - fixed gate and API-derived PR number
                [sys.executable, str(GATE), number, "--repo", repository, "--merge"],
                check=False,
                capture_output=True,
                text=True,
                timeout=gate_timeout,
            )
        except subprocess.TimeoutExpired:
            output = f"Gate timed out after its {gate_timeout}-second shared budget."
            state = "error"
            unexpected = True
            result = None
        else:
            output = (result.stdout + result.stderr).strip()
            state = "merged" if result.returncode == 0 else "deferred"
            if result.returncode not in DEFERRED | {0}:
                state = "error"
                unexpected = True
        if result is not None and result.returncode == 0:
            command = post_merge_command(pr, repository)
            if command is not None:
                handoff_timeout = shared_timeout(
                    deadline - time.monotonic(),
                    len(candidates) - index,
                    HANDOFF_TIMEOUT_SECONDS,
                )
                if handoff_timeout == 0:
                    output = "\n".join(
                        (
                            output,
                            "Post-merge handoff deferred because the shared budget is exhausted.",
                        )
                    )
                    state = "merged; post-merge handoff failed"
                    unexpected = True
                else:
                    try:
                        handoff = subprocess.run(  # noqa: S603 - trusted env command
                            command,
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=handoff_timeout,
                        )
                    except subprocess.TimeoutExpired:
                        timeout_message = (
                            f"Post-merge handoff timed out after {handoff_timeout} seconds."
                        )
                        output = "\n".join((output, timeout_message))
                        state = "merged; post-merge handoff failed"
                        unexpected = True
                    else:
                        output = "\n".join(
                            part
                            for part in (output, handoff.stdout.strip(), handoff.stderr.strip())
                            if part
                        )
                        if handoff.returncode != 0:
                            state = "merged; post-merge handoff failed"
                            unexpected = True
        lines.extend(
            [
                f"### PR #{number}: {state}",
                "",
                f"<pre>{html.escape(output)}</pre>",
                "",
            ]
        )
        print(f"PR #{number}: {state}\n{output}")
    _summary(lines)
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
