#!/usr/bin/env python3
"""Decide whether an agent may merge a pull request without a human reading it.

Turns the merge conditions in AGENTS.md and CLAUDE.md into checks. Prints one
line per finding and a verdict, and exits with it:

  0  READY    every condition holds; the agent may merge.
  10 SURFACE  mergeable, but a human must decide (a permission, credential,
              dependency, policy, intent or decision-record change, or a review
              thread closed without the author's reply).
  1  BLOCKED  not mergeable yet (checks, threads, conflicts or evidence).

Usage: merge_ready.py PR_NUMBER [--repo OWNER/NAME]
       merge_ready.py --self-test
Needs the GitHub CLI, authenticated with read access. Reads only.
"""

import json
import re
import subprocess
import sys

GREEN = {"success", "skipped", "neutral"}
PLACEHOLDER = re.compile(r"`command`\s*(→|->)\s*result", re.I)

# Paths whose change is a human decision in either repository, on either side
# of a rename or deletion.
DECISION_PATHS = (
    re.compile(r"^intent/"),
    re.compile(r"^policy\.yaml$"),
    re.compile(r"^policies/"),
    re.compile(r"^k8s/.*/policies/"),
    re.compile(r"^docs/decisions/"),
    re.compile(r"^docs/pdr/"),
    re.compile(r"^docs/[^/]*-DDR\.md$"),
    re.compile(r"^docs/product-requirements\.md$"),
    re.compile(r"^infrastructure/permanent/"),
)
DEPENDENCY_PATHS = re.compile(
    r"(^|/)(pyproject\.toml|uv\.lock|requirements[^/]*\.txt|package(-lock)?\.json|go\.(mod|sum))$"
)
WORKFLOW = re.compile(r"^\.github/(workflows|actions)/.+\.ya?ml$")
DOCKERFILE = re.compile(r"(^|/)Dockerfile[^/]*$")
YAML = re.compile(r"\.ya?ml$")
TERRAFORM = re.compile(r"\.tf$")

# (kind, which files, which changed lines) -> a line that grants a permission,
# reaches a credential or pulls in outside code. Each rule applies only to the
# files where that text means it, so prose and test fixtures do not trigger it.
LINE_RULES = (
    ("permission", WORKFLOW, re.compile(r"^[+-]\s*(permissions:|[a-z-]+:\s*write\b)")),
    ("credential", WORKFLOW, re.compile(r"^\+.*\$\{\{\s*secrets\.")),
    # A remote action; local ones (./.github/actions/...) are in this repository.
    ("dependency", WORKFLOW, re.compile(r"^\+\s*(-\s*)?uses:\s+(?![./])\S")),
    ("dependency", DOCKERFILE, re.compile(r"^\+\s*FROM\s")),
    ("dependency", YAML, re.compile(r"^\+\s*version:\s*['\"]?v?\d")),
    ("permission", TERRAFORM, re.compile(r'^[+-].*resource\s+"aws_iam_')),
)


def scope_findings(diff: str) -> list[str]:
    """Human-decision reasons found in a unified diff."""
    findings: list[str] = []
    old = new = ""
    for line in diff.splitlines():
        if line.startswith("--- "):
            old = line[6:] if line.startswith("--- a/") else ""
            continue
        if line.startswith("+++ "):
            new = line[6:] if line.startswith("+++ b/") else ""
            for path in dict.fromkeys(p for p in (old, new) if p):
                if any(rule.search(path) for rule in DECISION_PATHS):
                    findings.append(f"decision record, policy or scope file changed: {path}")
                if DEPENDENCY_PATHS.search(path):
                    findings.append(f"dependency manifest changed: {path}")
            continue
        path = new or old
        for kind, files, rule in LINE_RULES:
            if files.search(path) and rule.search(line):
                verb = "removes" if line.startswith("-") else "adds"
                findings.append(f"{verb} a {kind} in {path}: {line[1:].strip()[:80]}")
                break
    return list(dict.fromkeys(findings))


def has_verification(body: str) -> bool:
    """A '## Verification' section holding at least one real backticked command."""
    match = re.search(r"^#{2,3}\s*Verification\b(.*?)(?=^#{1,3}\s|\Z)", body, re.S | re.M | re.I)
    if not match:
        return False
    section = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.S)
    section = PLACEHOLDER.sub("", section)
    return any(
        code.strip() and code.strip() != "command" for code in re.findall(r"`([^`]+)`", section)
    )


def gh(*args: str) -> str:
    # A fixed argument list to the GitHub CLI on PATH, with no shell.
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return result.stdout


def gh_json_lines(*args: str) -> list[dict]:
    """Every page of a paginated call, one JSON object per line via --jq."""
    return [json.loads(line) for line in gh(*args).splitlines() if line.strip()]


def review_threads(owner: str, name: str, number: str) -> list[dict]:
    query = """
    query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100, after: $endCursor) {
            pageInfo { hasNextPage endCursor }
            nodes { isResolved comments(first: 100) { nodes { author { login } } } }
          }
        }
      }
    }"""
    return gh_json_lines(
        "api", "graphql", "--paginate",
        "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}",
        "-f", f"query={query}",
        "--jq", ".data.repository.pullRequest.reviewThreads.nodes[]",
    )  # fmt: skip


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    if not argv or not argv[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    number = argv[0]
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    else:
        repo = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
    owner, name = repo.split("/")
    pr = json.loads(
        gh("pr", "view", number, "-R", repo, "--json",
           "state,isDraft,mergeStateStatus,body,headRefOid,author")
    )  # fmt: skip
    blocked: list[str] = []
    surface: list[str] = []

    if pr["state"] != "OPEN" or pr["isDraft"]:
        draft = " draft" if pr["isDraft"] else ""
        blocked.append(f"pull request is {pr['state'].lower()}{draft}")
    if pr["mergeStateStatus"] != "CLEAN":
        blocked.append(f"merge state is {pr['mergeStateStatus']} (conflicts, behind, or checks)")

    sha = pr["headRefOid"]
    runs = gh_json_lines(
        "api", "--paginate", f"repos/{repo}/commits/{sha}/check-runs?per_page=100",
        "--jq", ".check_runs[]|{name,status,conclusion}",
    )  # fmt: skip
    # The newest status per context is the one that counts.
    latest: dict[str, str] = {}
    for status in gh_json_lines(
        "api", "--paginate", f"repos/{repo}/commits/{sha}/statuses?per_page=100",
        "--jq", ".[]|{context,state}",
    ):  # fmt: skip
        latest.setdefault(status["context"], status["state"])
    pending = [r["name"] for r in runs if r["status"] != "completed"]
    pending += [context for context, state in latest.items() if state == "pending"]
    failed = [
        r["name"] for r in runs if r["status"] == "completed" and r["conclusion"] not in GREEN
    ]
    failed += [context for context, state in latest.items() if state in ("failure", "error")]
    if not runs and not latest:
        blocked.append("no checks ran on the head commit")
    if pending:
        blocked.append(f"checks still running: {', '.join(pending)}")
    if failed:
        blocked.append(f"checks not green: {', '.join(failed)}")

    threads = review_threads(owner, name, number)
    author = pr["author"]["login"]
    unresolved = sum(not t["isResolved"] for t in threads)
    # A resolved thread needs the author's own reply after the finding.
    silent = sum(
        t["isResolved"]
        and not any(
            (c.get("author") or {}).get("login") == author for c in t["comments"]["nodes"][1:]
        )
        for t in threads
    )
    if unresolved:
        blocked.append(f"{unresolved} review thread(s) unresolved")
    if silent:
        surface.append(f"{silent} thread(s) resolved without a reply from {author}")

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
    diff = "\n".join(
        [
            "--- a/.github/workflows/ci.yml",
            "+++ b/.github/workflows/ci.yml",
            "+permissions:",
            "+      contents: write",
            "-      pull-requests: write",
            "+        uses: someone/action@v3",
            "+          token: ${{ secrets.DEPLOY_TOKEN }}",
            "+        uses: ./.github/actions/local",
            "--- a/applications/x/Dockerfile",
            "+++ b/applications/x/Dockerfile",
            "+FROM python:3.13-slim",
            "--- /dev/null",
            "+++ b/intent/security.md",
            "--- a/policy.yaml",
            "+++ /dev/null",
            "--- a/docs/decisions/0007-gate.md",
            "+++ b/docs/archive/0007-gate.md",
            "--- a/docs/DEPLOYMENT-PROFILES-DDR.md",
            "+++ b/docs/DEPLOYMENT-PROFILES-DDR.md",
            "--- a/k8s/profiles/local/policies/require-local-images.yaml",
            "+++ b/k8s/profiles/local/policies/require-local-images.yaml",
            "--- a/uv.lock",
            "+++ b/uv.lock",
            "--- a/k8s/infrastructure/flagger/helmrelease.yaml",
            "+++ b/k8s/infrastructure/flagger/helmrelease.yaml",
            '+      version: "1.46.0"',
            # Not findings: prose, and the gate's own test fixtures.
            "--- a/docs/README.md",
            "+++ b/docs/README.md",
            "+Prose about permissions: and write access, uses: someone/action.",
            "--- a/.claude/skills/merge-gate/merge_ready.py",
            "+++ b/.claude/skills/merge-gate/merge_ready.py",
            '+        "+          token: ${{ secrets.DEPLOY_TOKEN }}",',
        ]
    )
    found = scope_findings(diff)
    expected = [
        "adds a permission in .github/workflows/ci.yml: permissions:",
        "adds a permission in .github/workflows/ci.yml: contents: write",
        "removes a permission in .github/workflows/ci.yml: pull-requests: write",
        "adds a dependency in .github/workflows/ci.yml: uses: someone/action@v3",
        "adds a credential in .github/workflows/ci.yml: token: ${{ secrets.DEPLOY_TOKEN }}",
        "adds a dependency in applications/x/Dockerfile: FROM python:3.13-slim",
        "decision record, policy or scope file changed: intent/security.md",
        "decision record, policy or scope file changed: policy.yaml",
        "decision record, policy or scope file changed: docs/decisions/0007-gate.md",
        "decision record, policy or scope file changed: docs/DEPLOYMENT-PROFILES-DDR.md",
        "decision record, policy or scope file changed: "
        "k8s/profiles/local/policies/require-local-images.yaml",
        "dependency manifest changed: uv.lock",
        'adds a dependency in k8s/infrastructure/flagger/helmrelease.yaml: version: "1.46.0"',
    ]
    assert found == expected, "\n".join(found)
    assert has_verification("## Verification\n\n- `make check` → 594 passed\n## Scope\n")
    assert not has_verification("## Verification\n\n<!-- run things -->\n\n- `command` → result\n")
    assert not has_verification("## Verification\n\nIt works, trust me.\n")
    assert not has_verification("Verified locally with `make check`.")
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
