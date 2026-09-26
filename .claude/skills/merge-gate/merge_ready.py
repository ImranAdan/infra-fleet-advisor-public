#!/usr/bin/env python3
"""Decide whether an agent-authored pull request may merge.

Exit codes:
  0  READY    all mechanical and decision checks hold
  1  BLOCKED  evidence, CI, review, mergeability, or a judge rejection blocks it
 10  PARK     an owner-only category needs current-head owner approval
 11  JUDGE    an independent judge decision for this head commit is missing
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

Finding = tuple[str, str]

GREEN = {"success", "skipped", "neutral"}
PLACEHOLDER = re.compile(r"`command`\s*(→|->)\s*result", re.I)
POLICY_PATH = Path(__file__).with_name("decision-policy.toml")

PATH_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "merge-authority",
        re.compile(
            r"^(?:\.claude/skills/merge-gate/|\.github/workflows/merge-judge\.ya?ml$|"
            r"(?:AGENTS|CLAUDE)\.md$)"
        ),
        "merge authority changed",
    ),
    (
        "workflow",
        re.compile(r"^\.github/(?:workflows|actions)/"),
        "automation code changed",
    ),
    ("intent-policy", re.compile(r"^intent/"), "declared intent changed"),
    ("intent-policy", re.compile(r"^policy\.yaml$"), "advisor policy changed"),
    ("intent-policy", re.compile(r"^policies/"), "policy changed"),
    ("intent-policy", re.compile(r"^k8s/.*/policies/"), "cluster policy changed"),
    ("decision-record", re.compile(r"^docs/(?:decisions|pdr)/"), "decision record changed"),
    ("decision-record", re.compile(r"^docs/[^/]*-DDR\.md$"), "decision record changed"),
    (
        "product-requirements",
        re.compile(r"^docs/product-requirements\.md$"),
        "product requirements changed",
    ),
    (
        "permanent-infrastructure",
        re.compile(r"^infrastructure/permanent/"),
        "permanent infrastructure changed",
    ),
    (
        "dependency-manifest",
        re.compile(
            r"(^|/)(?:pyproject\.toml|uv\.lock|requirements[^/]*\.txt|"
            r"package(?:-lock)?\.json|go\.(?:mod|sum))$"
        ),
        "dependency manifest changed",
    ),
    (
        "iam",
        re.compile(r"^infrastructure/.*/(?:iam|[^/]*[-_]iam)\.tf$"),
        "IAM definition changed",
    ),
    (
        "permission-added",
        re.compile(r"(?:^|/)(?:rbac|clusterrole|rolebinding|role)[^/]*\.ya?ml$", re.I),
        "Kubernetes RBAC file changed",
    ),
)

WORKFLOW = re.compile(r"^\.github/(?:workflows|actions)/.+\.ya?ml$")
RBAC_FILE = re.compile(r"(?:^|/)(?:rbac|clusterrole|rolebinding|role)[^/]*\.ya?ml$", re.I)
DOCKERFILE = re.compile(r"(^|/)Dockerfile[^/]*$")
YAML = re.compile(r"\.ya?ml$")
TERRAFORM = re.compile(r"\.tf$")
PRIVILEGED_TRIGGER = re.compile(r"\b(?:pull_request_target|issue_comment|workflow_run)\b")


def _finding(category: str, description: str) -> Finding:
    return category, description


def _adds_privileged_trigger(text: str) -> bool:
    """Recognize mapping, scalar, list and flow-map GitHub event syntax."""
    if re.match(
        r"(?:-\s*)?['\"]?(?:pull_request_target|issue_comment|workflow_run)"
        r"['\"]?\s*(?::|$)",
        text,
    ):
        return True
    if not re.match(r"['\"]?on['\"]?\s*:", text):
        return False
    return bool(PRIVILEGED_TRIGGER.search(text))


def _adds_remote_action(text: str) -> bool:
    """Return whether an added uses value points outside this repository."""
    match = re.match(r"(?:-\s*)?uses:\s+(\S+)", text)
    if not match:
        return False
    target = match.group(1).strip("'\"")
    return not target.startswith(("./", "/", "$/"))


def _hunk_has_rbac_marker(lines: list[str], start: int) -> bool:
    """Report whether this unified-diff hunk contains unambiguous RBAC structure."""
    marker = re.compile(
        r"(?:kind:\s*(?:Cluster)?Role(?:Binding)?\b|"
        r"(?:verbs|apiGroups|resourceNames|nonResourceURLs|subjects|roleRef):)"
    )
    for candidate in lines[start + 1 :]:
        if candidate.startswith(("@@", "diff --git ")):
            break
        content = (
            candidate[1:].strip() if candidate.startswith((" ", "+", "-")) else candidate.strip()
        )
        if marker.match(content):
            return True
    return False


def _path_findings(path: str) -> list[Finding]:
    return [
        _finding(category, f"{description}: {path}")
        for category, pattern, description in PATH_RULES
        if pattern.search(path)
    ]


def _line_findings(path: str, line: str) -> list[Finding]:
    """Decision findings for one changed hunk line."""
    if not line.startswith(("+", "-")):
        return []
    added = line.startswith("+")
    text = line[1:].strip()
    verb = "adds" if added else "removes"
    findings: list[Finding] = []

    if WORKFLOW.search(path):
        if re.match(r"(?:permissions:|[a-z-]+:\s*write\b)", text):
            category = "permission-added" if added else "permission-removed"
            findings.append(
                _finding(category, f"{verb} a workflow permission in {path}: {text[:80]}")
            )
        if added and _adds_privileged_trigger(text):
            findings.append(
                _finding(
                    "merge-authority", f"adds a privileged workflow trigger in {path}: {text[:80]}"
                )
            )
        if added and re.search(
            r"(?:gh\s+pr\s+merge|mergePullRequest|owner-approved|merge-gate-judge)", text
        ):
            findings.append(
                _finding("merge-authority", f"adds merge-control logic in {path}: {text[:80]}")
            )
        if added and re.search(r"(?:\$\{\{\s*secrets(?:\.|\s*\[)|\bsecrets:\s*inherit\b)", text):
            findings.append(
                _finding("credential", f"adds a credential reference in {path}: {text[:80]}")
            )
        if added and _adds_remote_action(text):
            findings.append(_finding("dependency", f"adds a remote action in {path}: {text[:80]}"))

    if added and DOCKERFILE.search(path) and re.match(r"FROM\s", text):
        findings.append(_finding("dependency", f"adds a base image in {path}: {text[:80]}"))
    if added and YAML.search(path) and re.match(r"version:\s*['\"]?v?\d", text):
        findings.append(_finding("dependency", f"adds a chart version in {path}: {text[:80]}"))

    if TERRAFORM.search(path) and re.search(
        r"aws_iam_|\biam:[A-Za-z*]|['\"][a-z0-9-]+:[A-Za-z*]|"
        r"\b(?:actions|resources)\s*=|['\"]Resource['\"]\s*:",
        text,
        re.I,
    ):
        findings.append(_finding("iam", f"{verb} IAM configuration in {path}: {text[:80]}"))

    if YAML.search(path) and re.match(
        r"(?:kind:\s*(?:Cluster)?Role(?:Binding)?\b|verbs:|apiGroups:|roleRef:|subjects:)", text
    ):
        category = "permission-added" if added else "permission-removed"
        findings.append(_finding(category, f"{verb} Kubernetes RBAC in {path}: {text[:80]}"))

    return findings


def scope_findings(diff: str) -> list[Finding]:
    """Return structured decision findings from a unified diff."""
    findings: list[Finding] = []
    path = ""
    in_hunk = False
    rbac_indent: int | None = None
    rbac_key = ""
    lines = diff.splitlines()
    hunk_start = 0
    for index, line in enumerate(lines):
        header = re.match(r"^diff --git a/(.*) b/(.*)$", line)
        if header:
            in_hunk = False
            rbac_indent = None
            rbac_key = ""
            old, path = header.group(1), header.group(2)
            for changed in dict.fromkeys((old, path)):
                findings.extend(_path_findings(changed))
            continue
        if not in_hunk:
            if line.startswith("rename from "):
                findings.extend(_path_findings(line[len("rename from ") :]))
            elif line.startswith("+++ b/"):
                path = line[6:]
            elif line.startswith("@@"):
                in_hunk = True
                rbac_indent = None
                rbac_key = ""
                hunk_start = index
            continue
        if line.startswith("@@"):
            rbac_indent = None
            rbac_key = ""
            hunk_start = index
            continue
        content = line[1:] if line.startswith((" ", "+", "-")) else line
        stripped = content.strip()
        indent = len(content) - len(content.lstrip())
        rbac_match = re.match(
            r"(verbs|apiGroups|resources|resourceNames|nonResourceURLs|subjects|roleRef):",
            stripped,
        )
        is_rbac_key = (
            bool(YAML.search(path))
            and bool(rbac_match)
            and (
                rbac_match.group(1) != "resources"
                or bool(RBAC_FILE.search(path))
                or _hunk_has_rbac_marker(lines, hunk_start)
            )
        )
        if is_rbac_key:
            rbac_indent = indent
            rbac_key = rbac_match.group(1) if rbac_match else ""
        elif (
            rbac_indent is not None
            and stripped
            and not stripped.startswith("-")
            and indent <= rbac_indent
        ):
            rbac_indent = None
            rbac_key = ""
        if (
            rbac_indent is not None
            and not is_rbac_key
            and line.startswith(("+", "-"))
            and (rbac_key != "resources" or stripped.startswith("-"))
        ):
            category = "permission-added" if line.startswith("+") else "permission-removed"
            verb = "adds" if line.startswith("+") else "removes"
            findings.append(
                _finding(category, f"{verb} a Kubernetes RBAC value in {path}: {stripped[:80]}")
            )
        findings.extend(_line_findings(path, line))
    return list(dict.fromkeys(findings))


def load_policy(path: Path = POLICY_PATH) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Load rules by category and the judge settings, failing closed."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, str]] = {}
    for raw in data.get("rule", []):
        if not isinstance(raw, dict):
            raise ValueError("each policy rule must be a table")
        required = ("id", "category", "decider", "guidance")
        if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
            raise ValueError("each policy rule needs non-empty id, category, decider and guidance")
        if raw["decider"] not in {"judge", "owner"}:
            raise ValueError(f"invalid decider for {raw['category']}: {raw['decider']}")
        if raw["category"] in rules:
            raise ValueError(f"duplicate policy category: {raw['category']}")
        rules[raw["category"]] = {key: raw[key] for key in required}
    judge = data.get("judge")
    if not isinstance(judge, dict) or any(
        not isinstance(judge.get(key), str) or not judge[key].strip()
        for key in ("trusted_author", "model")
    ):
        raise ValueError("policy needs judge.trusted_author and judge.model")
    return rules, {"trusted_author": judge["trusted_author"], "model": judge["model"]}


def judge_decision(
    comments: list[dict[str, str]], sha: str, trusted_author: str
) -> tuple[str, frozenset[str]] | None:
    """Return the newest well-formed trusted decision for this exact head SHA."""
    marker = re.escape(f"<!-- merge-gate-judge sha={sha} -->")
    pattern = re.compile(
        rf"\A{marker}\nDECISION: (APPROVE|REJECT)\nRULES: ([^\n]*)",
    )
    for comment in reversed(comments):
        if comment.get("author") != trusted_author:
            continue
        match = pattern.search(comment.get("body", ""))
        if match:
            rule_ids = frozenset(item.strip() for item in match.group(2).split(",") if item.strip())
            return match.group(1), rule_ids
    return None


def owner_approval(comments: list[dict[str, str]], sha: str, trusted_author: str) -> bool:
    """Return whether the trusted workflow recorded approval for this exact head."""
    marker = f"<!-- merge-gate-owner-approved sha={sha} -->"
    for comment in reversed(comments):
        if comment.get("author") != trusted_author:
            continue
        lines = comment.get("body", "").splitlines()
        if len(lines) >= 2 and lines[0] == marker:
            if lines[1] == "OWNER-APPROVED: true":
                return True
            if lines[1] == "OWNER-APPROVED: false":
                return False
    return False


def owner_label_approval(events: list[dict[str, str]], repository_owner: str) -> bool:
    """Require the newest owner-approved label event to come from the owner."""
    if not repository_owner:
        return False
    for event in reversed(events):
        if event.get("label") != "owner-approved":
            continue
        return (
            event.get("event") == "labeled"
            and event.get("actor", "").casefold() == repository_owner.casefold()
        )
    return False


def decide(
    findings: list[Finding],
    rules: dict[str, dict[str, str]],
    labels: set[str],
    decision: tuple[str, frozenset[str]] | None,
    current_owner_approval: bool = False,
) -> tuple[str, list[str]]:
    """Apply the policy to findings after mechanical checks have passed."""
    categories = list(dict.fromkeys(category for category, _ in findings))
    owner_categories = [
        category
        for category in categories
        if category not in rules or rules[category]["decider"] == "owner"
    ]
    judge_rules = {
        rules[category]["id"]
        for category in categories
        if category in rules and rules[category]["decider"] == "judge"
    }

    if decision and decision[0] == "REJECT" and judge_rules.intersection(decision[1]):
        rejected = ", ".join(sorted(judge_rules.intersection(decision[1])))
        return "BLOCKED", [f"independent judge rejected rule(s): {rejected}"]
    if owner_categories and ("owner-approved" not in labels or not current_owner_approval):
        return "PARK", [f"owner decision required for: {', '.join(owner_categories)}"]
    if judge_rules and (
        not decision or decision[0] != "APPROVE" or not judge_rules.issubset(decision[1])
    ):
        missing = (
            judge_rules if not decision or decision[0] != "APPROVE" else judge_rules - decision[1]
        )
        return "JUDGE", [f"independent judge approval required for: {', '.join(sorted(missing))}"]
    return "READY", []


def has_verification(body: str) -> bool:
    """A Verification section holding at least one real command and result."""
    match = re.search(r"^#{2,3}\s*Verification\b(.*?)(?=^#{1,3}\s|\Z)", body, re.S | re.M | re.I)
    if not match:
        return False
    section = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.S)
    section = PLACEHOLDER.sub("", section)
    return any(
        found.group(1).strip() not in ("", "command")
        for found in re.finditer(r"`([^`]+)`[^\n`]*?(?:→|->)\s*(\S[^\n]*)", section)
    )


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return result.stdout


def merge_pull_request(number: str, repo: str, sha: str) -> None:
    """Merge only if GitHub still reports the exact head evaluated by this gate."""
    gh(
        "pr",
        "merge",
        number,
        "-R",
        repo,
        "--merge",
        "--match-head-commit",
        sha,
    )


def gh_json_lines(*args: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in gh(*args).splitlines() if line.strip()]


def review_threads(owner: str, name: str, number: str) -> list[dict[str, Any]]:
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
        "api",
        "graphql",
        "--paginate",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={number}",
        "-f",
        f"query={query}",
        "--jq",
        ".data.repository.pullRequest.reviewThreads.nodes[]",
    )


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    if not argv or not argv[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    number = argv[0]
    repo = (
        argv[argv.index("--repo") + 1]
        if "--repo" in argv
        else gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
    )
    owner, name = repo.split("/")
    pr = json.loads(
        gh(
            "pr",
            "view",
            number,
            "-R",
            repo,
            "--json",
            "state,isDraft,mergeStateStatus,body,headRefOid,author,labels",
        )
    )
    blocked: list[str] = []
    if pr["state"] != "OPEN" or pr["isDraft"]:
        draft = " draft" if pr["isDraft"] else ""
        blocked.append(f"pull request is {pr['state'].lower()}{draft}")
    if pr["mergeStateStatus"] != "CLEAN":
        blocked.append(f"merge state is {pr['mergeStateStatus']} (conflicts, behind, or checks)")

    sha = pr["headRefOid"]
    runs = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100&filter=latest",
        "--jq",
        ".check_runs[]|{name,status,conclusion}",
    )
    latest: dict[str, str] = {}
    for status in gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/commits/{sha}/statuses?per_page=100",
        "--jq",
        ".[]|{context,state}",
    ):
        latest.setdefault(status["context"], status["state"])
    pending = [run["name"] for run in runs if run["status"] != "completed"]
    pending += [context for context, state in latest.items() if state == "pending"]
    failed = [
        run["name"]
        for run in runs
        if run["status"] == "completed" and run["conclusion"] not in GREEN
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
    unresolved = sum(not thread["isResolved"] for thread in threads)
    silent = sum(
        thread["isResolved"]
        and not any(
            (comment.get("author") or {}).get("login") == author
            for comment in thread["comments"]["nodes"][1:]
        )
        for thread in threads
    )
    if unresolved:
        blocked.append(f"{unresolved} review thread(s) unresolved")
    if silent:
        blocked.append(f"{silent} thread(s) resolved without a reply from {author}")
    if not has_verification(pr["body"] or ""):
        blocked.append("no '## Verification' section with commands and results")

    findings = scope_findings(gh("pr", "diff", number, "-R", repo))
    print(f"{repo}#{number} at {sha[:12]}: {len(runs)} check runs, {len(threads)} threads")
    for category, description in findings:
        print(f"DECISION {category}: {description}")
    if blocked:
        for reason in blocked:
            print(f"BLOCKED  {reason}")
        print("verdict: BLOCKED")
        return 1

    try:
        rules, judge = load_policy()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"PARK  decision policy is invalid: {exc}")
        print("verdict: PARK")
        return 10
    comments = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{number}/comments?per_page=100",
        "--jq",
        ".[]|{body,author:.user.login}",
    )
    decision = judge_decision(comments, sha, judge["trusted_author"])
    labels = {label["name"] for label in pr["labels"]}
    owner_events = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{number}/events?per_page=100",
        "--jq",
        '.[]|select(.label.name=="owner-approved")|{event,actor:.actor.login,label:.label.name}',
    )
    verdict, reasons = decide(
        findings,
        rules,
        labels,
        decision,
        owner_approval(comments, sha, judge["trusted_author"])
        and owner_label_approval(owner_events, owner),
    )
    for reason in reasons:
        print(f"{verdict}  {reason}")
    print(f"verdict: {verdict}")
    if verdict == "READY":
        if "--merge" in argv:
            merge_pull_request(number, repo, sha)
            print(f"merged {repo}#{number} at {sha}")
        else:
            print(
                f"merge: rerun this gate with --merge; GitHub will require the checked head {sha}"
            )
    return {"READY": 0, "BLOCKED": 1, "PARK": 10, "JUDGE": 11}[verdict]


def _file(path: str, *lines: str, old: str | None = None) -> list[str]:
    return [
        f"diff --git a/{old or path} b/{path}",
        f"--- a/{old or path}",
        f"+++ b/{path}",
        "@@ -1,3 +1,3 @@",
        *lines,
    ]


def self_test() -> int:
    diff = "\n".join(
        [
            *_file(
                ".github/workflows/ci.yml",
                "+permissions:",
                "+      contents: write",
                "-      pull-requests: write",
                "+pull_request_target:",
                "+on: pull_request_target",
                "+on: [push, pull_request_target]",
                "+        uses: someone/action@0123456789abcdef",
                "+          token: ${{ secrets.DEPLOY_TOKEN }}",
                "+          other: ${{ secrets['OTHER_TOKEN'] }}",
                "+        secrets: inherit",
                "+        uses: ./.github/actions/local",
                "+        uses: $/.github/actions/build",
                '+        uses: "$/actions/quoted"',
            ),
            *_file("applications/x/Dockerfile", "+FROM python:3.13-slim"),
            *_file(
                "infrastructure/ephemeral/iam.tf",
                '- actions = ["s3:GetObject"]',
                '+ actions = ["iam:*"]',
            ),
            *_file(
                "infrastructure/staging/flux-image-reflector.tf",
                '-        "ecr:GetAuthorizationToken",',
                '+        "ecr:*",',
            ),
            *_file(
                "infrastructure/staging/resource-scope.tf",
                '-      "Resource": "arn:aws:s3:::one-bucket",',
                '+      "Resource": "*",',
            ),
            *_file("k8s/rbac.yaml", "+kind: ClusterRole", '+  verbs: ["*"]'),
            *_file(
                "k8s/flux-system/flux-system/gotk-components.yaml",
                "   verbs:",
                "-  - get",
                '+  - "*"',
            ),
            *_file(
                "k8s/applications/platform/deployment.yaml",
                "     resources:",
                "-      cpu: 100m",
                "+      cpu: 500m",
            ),
            *_file(
                "k8s/applications/kustomization.yaml",
                " resources:",
                "+- deployment.yaml",
            ),
            "diff --git a/intent/security.md b/intent/security.md",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/intent/security.md",
            "@@ -0,0 +1 @@",
            "+- Check: `new_check`",
            "diff --git a/docs/decisions/0007-gate.md b/docs/archive/0007-gate.md",
            "similarity index 100%",
            "rename from docs/decisions/0007-gate.md",
            "rename to docs/archive/0007-gate.md",
            "diff --git a/policies/logo.png b/policies/logo.png",
            "Binary files a/policies/logo.png and b/policies/logo.png differ",
            *_file("docs/DEPLOYMENT-PROFILES-DDR.md", "+A decision."),
            *_file("docs/product-requirements.md", "+A requirement."),
            *_file("uv.lock", "+name = x"),
            *_file("k8s/infrastructure/flagger/helmrelease.yaml", '+      version: "1.46.0"'),
            *_file(".claude/skills/merge-gate/merge_ready.py", "+def main(): return 0"),
            *_file("docs/README.md", "+Prose about permissions and secrets.DEPLOY_TOKEN."),
            *_file(".github/workflows/lint.yml", "--- a/not-a-header", "+  contents: write"),
        ]
    )
    found = scope_findings(diff)
    categories = [category for category, _ in found]
    assert categories.count("permission-added") >= 7, found
    assert categories.count("permission-removed") >= 2, found
    assert categories.count("merge-authority") >= 4, found
    assert categories.count("workflow") == 2, found
    assert categories.count("iam") >= 2, found
    assert any(category == "iam" and "ecr:*" in description for category, description in found)
    assert any(
        category == "iam" and "resource-scope.tf" in description for category, description in found
    )
    assert any(
        category == "permission-added" and "gotk-components.yaml" in description
        for category, description in found
    )
    assert not any(
        category.startswith("permission-")
        and ("deployment.yaml" in description or "kustomization.yaml" in description)
        for category, description in found
    )
    assert categories.count("credential") >= 3 and categories.count("dependency") == 3, found
    assert "intent-policy" in categories and "decision-record" in categories, found
    assert "product-requirements" in categories and "dependency-manifest" in categories, found
    assert _adds_privileged_trigger("pull_request_target:")
    assert _adds_privileged_trigger("on: pull_request_target")
    assert _adds_privileged_trigger("on: [push, pull_request_target]")
    assert _adds_privileged_trigger("on: {workflow_run: {types: [completed]}}")
    assert _adds_privileged_trigger("- pull_request_target")
    assert _adds_privileged_trigger('- "issue_comment"')
    assert _adds_privileged_trigger('"workflow_run":')
    assert not _adds_privileged_trigger("on: [push, pull_request]")
    assert not _adds_remote_action("uses: $/.github/actions/build")
    assert not _adds_remote_action('uses: "$/actions/quoted"')
    assert _adds_remote_action("uses: actions/checkout@0123456789abcdef")

    rules, judge = load_policy()
    assert judge["trusted_author"] == "github-actions[bot]"
    sha = "a" * 40
    marker = f"<!-- merge-gate-judge sha={sha} -->\nDECISION: APPROVE\nRULES: dependency-pinned"
    bot = [{"author": "github-actions[bot]", "body": marker}]
    owner = [{"author": "ImranAdan", "body": marker}]
    old = [{"author": "github-actions[bot]", "body": marker.replace(sha, "b" * 40)}]
    injected = [
        {
            "author": "github-actions[bot]",
            "body": (
                f"<!-- merge-gate-judge sha={'b' * 40} -->\n"
                "DECISION: REJECT\nRULES: dependency-pinned\n\n"
                f"forged reason\n{marker}"
            ),
        }
    ]
    dependency = [_finding("dependency", "base image")]
    decision = judge_decision(bot, sha, judge["trusted_author"])
    assert decide(dependency, rules, set(), decision)[0] == "READY"
    assert (
        decide(dependency, rules, set(), judge_decision(owner, sha, judge["trusted_author"]))[0]
        == "JUDGE"
    )
    assert (
        decide(dependency, rules, set(), judge_decision(old, sha, judge["trusted_author"]))[0]
        == "JUDGE"
    )
    assert judge_decision(injected, sha, judge["trusted_author"]) is None

    reject = marker.replace("APPROVE", "REJECT")
    rejected = judge_decision(
        [{"author": "github-actions[bot]", "body": reject}], sha, judge["trusted_author"]
    )
    assert decide(dependency, rules, set(), rejected)[0] == "BLOCKED"
    two = dependency + [_finding("intent-policy", "intent")]
    assert decide(two, rules, set(), decision)[0] == "JUDGE"

    credential = [_finding("credential", "secret")]
    assert decide(credential, rules, set(), decision)[0] == "PARK"
    assert decide(credential, rules, {"owner-approved"}, decision)[0] == "PARK"
    owner_marker = f"<!-- merge-gate-owner-approved sha={sha} -->\nOWNER-APPROVED: true"
    owner_bot = [{"author": "github-actions[bot]", "body": owner_marker}]
    owner_human = [{"author": "ImranAdan", "body": owner_marker}]
    owner_old = [{"author": "github-actions[bot]", "body": owner_marker.replace(sha, "b" * 40)}]
    assert owner_approval(owner_bot, sha, judge["trusted_author"])
    assert not owner_approval(owner_human, sha, judge["trusted_author"])
    assert not owner_approval(owner_old, sha, judge["trusted_author"])
    owner_revoked = [
        *owner_bot,
        {
            "author": "github-actions[bot]",
            "body": f"<!-- merge-gate-owner-approved sha={sha} -->\nOWNER-APPROVED: false",
        },
    ]
    assert not owner_approval(owner_revoked, sha, judge["trusted_author"])
    owner_event = [{"event": "labeled", "actor": "ImranAdan", "label": "owner-approved"}]
    non_owner_event = [
        *owner_event,
        {"event": "labeled", "actor": "contributor", "label": "owner-approved"},
    ]
    removed_event = [
        *owner_event,
        {"event": "unlabeled", "actor": "ImranAdan", "label": "owner-approved"},
    ]
    assert owner_label_approval(owner_event, "ImranAdan")
    assert not owner_label_approval(non_owner_event, "ImranAdan")
    assert not owner_label_approval(removed_event, "ImranAdan")
    assert not owner_label_approval(owner_event, "another-owner")
    assert decide(credential, rules, {"owner-approved"}, decision, True)[0] == "READY"
    authority = [_finding("merge-authority", "gate")]
    authority_approve = ("APPROVE", frozenset({"merge-authority"}))
    assert decide(authority, rules, set(), authority_approve)[0] == "PARK"
    assert decide([_finding("unlisted", "new")], rules, set(), decision)[0] == "PARK"

    assert has_verification("## Verification\n\n- `make check` → 594 passed\n## Scope\n")
    assert has_verification("## Verification\n- `./fleet test` -> passed all six stages\n")
    assert not has_verification("## Verification\n\n- `command` → result\n")
    assert not has_verification("Verified locally: `make check` → 594 passed.")

    calls: list[tuple[str, ...]] = []
    original_gh = globals()["gh"]

    def fake_gh(*args: str) -> str:
        calls.append(args)
        return ""

    globals()["gh"] = fake_gh
    try:
        merge_pull_request("7", "owner/repo", sha)
    finally:
        globals()["gh"] = original_gh
    assert calls == [
        (
            "pr",
            "merge",
            "7",
            "-R",
            "owner/repo",
            "--merge",
            "--match-head-commit",
            sha,
        )
    ]
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
