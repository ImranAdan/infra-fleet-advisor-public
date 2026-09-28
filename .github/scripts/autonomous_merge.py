#!/usr/bin/env python3
"""Merge same-repository pull requests that opt into the evidence gate."""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MARKER = "<!-- autonomous-merge -->"
GATE = Path(".claude/skills/merge-gate/merge_ready.py")
DEFERRED = {1, 10, 11}


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
    del os.environ["AUTONOMOUS_MERGE_POST_MERGE_WORKFLOW"]
    del os.environ["AUTONOMOUS_MERGE_POST_MERGE_HEAD"]
    print("self-test passed")
    return 0


def _open_pull_requests(repository: str) -> list[dict[str, Any]]:
    result = subprocess.run(  # noqa: S603 - fixed gh argv, validated repository
        [
            "/usr/bin/env",
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,body,createdAt,isDraft,headRefName,headRepository,headRepositoryOwner",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise ValueError("GitHub returned a non-list pull-request response")
    return value


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

    candidates = [
        pr
        for pr in _open_pull_requests(repository)
        if eligible(pr, repository, datetime.now(UTC), minimum_age)
    ]
    lines = ["## Autonomous merge", ""]
    unexpected = False
    if not candidates:
        lines.append("No eligible pull request is ready for evaluation.")
    for pr in candidates:
        number = str(pr["number"])
        result = subprocess.run(  # noqa: S603 - fixed gate and API-derived PR number
            [sys.executable, str(GATE), number, "--repo", repository, "--merge"],
            check=False,
            capture_output=True,
            text=True,
        )
        output = (result.stdout + result.stderr).strip()
        state = "merged" if result.returncode == 0 else "deferred"
        if result.returncode not in DEFERRED | {0}:
            state = "error"
            unexpected = True
        if result.returncode == 0:
            command = post_merge_command(pr, repository)
            if command is not None:
                handoff = subprocess.run(  # noqa: S603 - command is built from trusted env only
                    command, check=False, capture_output=True, text=True
                )
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
