#!/usr/bin/env python3
"""Decide whether an agent may merge a pull request without a human reading it.

Turns the CLAUDE.md standing grant into checks. Prints one line per check and a
verdict, and exits with it:

  0  READY    every condition holds; the agent may merge.
  10 SURFACE  mergeable, but a human must decide (scope, permission, credential,
              dependency or decision-record change, or a thread closed silently).
  1  BLOCKED  not mergeable yet (checks, threads, conflicts, evidence).

Usage: merge_ready.py PR_NUMBER [--repo OWNER/NAME]
       merge_ready.py --self-test
Needs the GitHub CLI, authenticated with read access. Reads only.
"""

import json
import re
import subprocess
import sys

GREEN = {"success", "skipped", "neutral"}

# Diff paths whose change is a human decision here, whatever the content.
DECISION_PATHS = (
    re.compile(r"^intent/"),
    re.compile(r"^policy\.yaml$"),
    re.compile(r"^docs/pdr/"),
    re.compile(r"^docs/product-requirements\.md$"),
    re.compile(r"^infrastructure/permanent/"),
)
DEPENDENCY_PATHS = re.compile(
    r"(^|/)(pyproject\.toml|uv\.lock|requirements[^/]*\.txt|package(-lock)?\.json|go\.(mod|sum))$"
)
# Added lines that grant a permission, reach a credential or pull in code.
ADDED_LINE_RULES = (
    ("permission", re.compile(r"^\+\s*(permissions:|[a-z-]+:\s*write\b)")),
    ("credential", re.compile(r"^\+.*\$\{\{\s*secrets\.")),
    # A remote action; local ones (./.github/actions/...) are in this repo.
    ("dependency", re.compile(r"^\+\s*(-\s*)?uses:\s+(?![./])\S")),
    ("dependency", re.compile(r"^\+\s*FROM\s")),
    ("dependency", re.compile(r"^\+\s*version:\s*['\"]?v?\d")),
    ("permission", re.compile(r'^\+.*resource\s+"aws_iam_')),
)


def scope_findings(diff: str) -> list[str]:
    """Human-decision reasons found in a unified diff."""
    findings: list[str] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            if any(rule.search(path) for rule in DECISION_PATHS):
                findings.append(f"decision record or scope file changed: {path}")
            if DEPENDENCY_PATHS.search(path):
                findings.append(f"dependency manifest changed: {path}")
            continue
        if line.startswith("+++") or not line.startswith("+"):
            continue
        for kind, rule in ADDED_LINE_RULES:
            if rule.search(line):
                findings.append(f"adds a {kind} in {path}: {line[1:].strip()[:80]}")
                break
    return list(dict.fromkeys(findings))


def has_verification(body: str) -> bool:
    """A '## Verification' section holding at least one backticked command."""
    match = re.search(r"^#{2,3}\s*Verification\b(.*?)(?=^#{1,3}\s|\Z)", body, re.S | re.M | re.I)
    return bool(match and "`" in match.group(1))


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    if not argv or not argv[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    number = argv[0]
    repo = argv[argv.index("--repo") + 1] if "--repo" in argv else gh(
        "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"
    ).strip()
    owner, name = repo.split("/")
    pr = json.loads(gh("pr", "view", number, "-R", repo, "--json",
                       "state,isDraft,mergeStateStatus,body,headRefOid"))
    blocked: list[str] = []
    surface: list[str] = []

    if pr["state"] != "OPEN" or pr["isDraft"]:
        blocked.append(f"pull request is {pr['state'].lower()}{' draft' if pr['isDraft'] else ''}")
    if pr["mergeStateStatus"] != "CLEAN":
        blocked.append(f"merge state is {pr['mergeStateStatus']} (conflicts, behind, or checks)")

    sha = pr["headRefOid"]
    runs = json.loads(gh("api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"))["check_runs"]
    statuses = json.loads(gh("api", f"repos/{repo}/commits/{sha}/status"))["statuses"]
    pending = [r["name"] for r in runs if r["status"] != "completed"]
    pending += [s["context"] for s in statuses if s["state"] == "pending"]
    failed = [r["name"] for r in runs if r["status"] == "completed" and r["conclusion"] not in GREEN]
    failed += [s["context"] for s in statuses if s["state"] in ("failure", "error")]
    if not runs and not statuses:
        blocked.append("no checks ran on the head commit")
    if pending:
        blocked.append(f"checks still running: {', '.join(pending)}")
    if failed:
        blocked.append(f"checks not green: {', '.join(failed)}")

    query = (
        f'{{repository(owner:"{owner}",name:"{name}"){{pullRequest(number:{number}){{'
        "reviewThreads(first:100){nodes{isResolved comments(first:2){totalCount}}}}}}"
    )
    threads = json.loads(gh("api", "graphql", "-f", f"query={query}"))["data"]["repository"][
        "pullRequest"]["reviewThreads"]["nodes"]
    unresolved = sum(not t["isResolved"] for t in threads)
    silent = sum(t["isResolved"] and t["comments"]["totalCount"] < 2 for t in threads)
    if unresolved:
        blocked.append(f"{unresolved} review thread(s) unresolved")
    if silent:
        surface.append(f"{silent} thread(s) resolved without a reply saying what changed")

    if not has_verification(pr["body"] or ""):
        blocked.append("no '## Verification' section with the commands and results that prove it")
    surface += scope_findings(gh("pr", "diff", number, "-R", repo))

    print(f"{repo}#{number} at {sha[:12]}: {len(runs)} check runs, {len(threads)} threads")
    for reason in blocked:
        print(f"BLOCKED  {reason}")
    for reason in surface:
        print(f"SURFACE  {reason}")
    if blocked:
        print("verdict: BLOCKED")
        return 1
    if surface:
        print("verdict: SURFACE: mergeable, but a human decides")
        return 10
    print("verdict: READY")
    return 0


def self_test() -> int:
    diff = "\n".join([
        "+++ b/.github/workflows/ci.yml",
        "+permissions:",
        "+      contents: write",
        "+        uses: someone/action@v3",
        "+          token: ${{ secrets.DEPLOY_TOKEN }}",
        "+        uses: ./.github/actions/local",
        "+++ b/applications/x/Dockerfile",
        "+FROM python:3.13-slim",
        "+++ b/intent/security.md",
        "+- Check: `new_check`",
        "+++ b/uv.lock",
        "+++ b/k8s/infrastructure/flagger/helmrelease.yaml",
        '+      version: "1.46.0"',
        "+++ b/docs/README.md",
        "+Words that mention permissions: and write access in prose.",
    ])
    found = scope_findings(diff)
    expected = [
        "adds a permission in .github/workflows/ci.yml: permissions:",
        "adds a permission in .github/workflows/ci.yml: contents: write",
        "adds a dependency in .github/workflows/ci.yml: uses: someone/action@v3",
        "adds a credential in .github/workflows/ci.yml: token: ${{ secrets.DEPLOY_TOKEN }}",
        "adds a dependency in applications/x/Dockerfile: FROM python:3.13-slim",
        "decision record or scope file changed: intent/security.md",
        "dependency manifest changed: uv.lock",
        'adds a dependency in k8s/infrastructure/flagger/helmrelease.yaml: version: "1.46.0"',
    ]
    assert found == expected, "\n".join(found)
    assert has_verification("## Verification\n\n`make check` passes (594 tests).\n## Notes\n")
    assert not has_verification("## Verification\n\nIt works, trust me.\n")
    assert not has_verification("Verified locally.")
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
