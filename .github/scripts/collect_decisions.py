#!/usr/bin/env python3
"""Collect the owner's answers on "Decision needed" issues, so nobody has to
report back that a decision was made.

For each open issue labelled needs-decision (or one issue, given its number):
read the decision cards from the body (`### D1 · …`), read the repository
owner's `D1: A` answers from the comments (the newest answer per card wins),
then keep one summary comment up to date and relabel the issue:

  every card answered  -> label decided, remove needs-decision
  some cards answered  -> label partially-decided, keep needs-decision

Open decided issues stay watched, so a revised answer updates the record until
an agent acts on it and closes the issue.

The summary carries a machine-readable record for agents:
  <!-- decisions {"D1": "A", ...} -->
Comment text is data: it is parsed, bounded and quoted, never executed.

Usage: collect_decisions.py [ISSUE_NUMBER] [--repo OWNER/NAME] [--dry-run]
       collect_decisions.py --self-test
Runs in GitHub Actions with GH_TOKEN (issues: write); --dry-run only reads.
"""

import json
import re
import subprocess
import sys

CARD = re.compile(r"^#{2,4}\s*(D\d+)\b\s*[·:.-]?\s*(.*)$", re.M)
ANSWER = re.compile(r"^\s*(D\d+)\s*:\s*(.+?)\s*$", re.M)
SUMMARY_MARKER = "<!-- decision-collector -->"
NEEDED, DECIDED, PARTIAL = "needs-decision", "decided", "partially-decided"


def cards(body: str) -> dict[str, str]:
    """Decision card ids and titles, in order."""
    return {m.group(1): m.group(2).strip()[:120] for m in CARD.finditer(body or "")}


def answers(comments: list[dict], owner: str, known: dict[str, str]) -> dict[str, dict]:
    """The owner's newest answer to each known card, outside code fences."""
    found: dict[str, dict] = {}
    for comment in comments:
        if comment["author"] != owner or SUMMARY_MARKER in comment["body"]:
            continue
        # Reply templates are often pasted inside ``` fences; answers count either way,
        # but quoted lines ("> D1: A") are someone else's words.
        text = re.sub(r"^\s*```.*$", "", comment["body"], flags=re.M)
        for match in ANSWER.finditer(text):
            card = match.group(1)
            if card in known and not match.group(0).lstrip().startswith(">"):
                found[card] = {"answer": match.group(2)[:200], "url": comment["url"]}
    return found


def summary(known: dict[str, str], decided: dict[str, dict]) -> str:
    """The summary comment body: a table for people, a record for agents."""
    open_cards = [card for card in known if card not in decided]
    rows = "\n".join(
        f"| {card} | {title} | "
        + (
            f"**{decided[card]['answer']}** ([answer]({decided[card]['url']}))"
            if card in decided
            else "open"
        )
        + " |"
        for card, title in known.items()
    )
    record = json.dumps({card: decided[card]["answer"] for card in known if card in decided})
    status = (
        "All decisions are in. Agents pick this up from the `decided` label; "
        "nobody needs to report back."
        if not open_cards
        else f"Still open: {', '.join(open_cards)}. Reply with `{open_cards[0]}: <option>`."
    )
    return (
        f"{SUMMARY_MARKER}\n<!-- decisions {record} -->\n"
        "### Decisions recorded\n\n| Card | Question | Decision |\n|---|---|---|\n"
        f"{rows}\n\n{status}\n"
    )


def gh(*args: str) -> str:
    # A fixed argument list to the GitHub CLI on PATH, with no shell.
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return result.stdout


def collect(repo: str, number: int, dry_run: bool) -> str:
    issue = json.loads(gh("api", f"repos/{repo}/issues/{number}"))
    labels = {label["name"] for label in issue["labels"]}
    # Decided issues stay watched until closed: the owner may still revise.
    if issue["state"] != "open" or not labels & {NEEDED, PARTIAL, DECIDED}:
        return f"#{number}: not an open decision issue"
    known = cards(issue["body"])
    if not known:
        return f"#{number}: no decision cards found"
    comments = [
        json.loads(line)
        for line in gh(
            "api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100",
            "--jq", ".[]|{id, body, url: .html_url, author: .user.login}",
        ).splitlines()
        if line.strip()
    ]  # fmt: skip
    owner = repo.split("/")[0]
    decided = answers(comments, owner, known)
    if not decided:
        return f"#{number}: waiting for the owner's first answer"
    body = summary(known, decided)
    complete = len(decided) == len(known)
    if dry_run:
        return f"#{number}: would record {len(decided)}/{len(known)}\n{body}"
    # Exactly one summary: keep the first, update it in place, delete strays
    # (left by an older version or an overlapping run) so no stale record stays.
    existing = [c for c in comments if SUMMARY_MARKER in c["body"]]
    for stray in existing[1:]:
        gh("api", "-X", "DELETE", f"repos/{repo}/issues/comments/{stray['id']}")
    if not existing:
        gh("api", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}")
    elif existing[0]["body"] != body:
        comment = existing[0]["id"]
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{comment}", "-f", f"body={body}")
    add, remove = ([DECIDED], [NEEDED, PARTIAL]) if complete else ([PARTIAL], [])
    for label in add:
        gh("api", f"repos/{repo}/issues/{number}/labels", "-f", f"labels[]={label}")
    for label in remove:
        if label in labels:
            gh("api", "-X", "DELETE", f"repos/{repo}/issues/{number}/labels/{label}")
    return (
        f"#{number}: recorded {len(decided)}/{len(known)} ({'decided' if complete else 'partial'})"
    )


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    dry_run = "--dry-run" in argv
    repo = (
        argv[argv.index("--repo") + 1]
        if "--repo" in argv
        else gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
    )
    numbers = [int(a) for a in argv if a.isdigit()]
    if not numbers:
        numbers = [
            int(n)
            for label in (NEEDED, PARTIAL, DECIDED)
            for n in gh("issue", "list", "-R", repo, "--state", "open", "--label", label,
                        "--json", "number", "--jq", ".[].number").split()
        ]  # fmt: skip
    for number in sorted(set(numbers)):
        print(collect(repo, number, dry_run))
    return 0


def self_test() -> int:
    body = "### D1 · Who is the judge?\n...\n### D2 · Scope\n...\n### D3 · Model\n"
    known = cards(body)
    assert known == {"D1": "Who is the judge?", "D2": "Scope", "D3": "Model"}, known
    comments = [
        {"author": "owner", "body": "```\nD1: A\nD2: as above\n```", "url": "u1"},
        {"author": "someone", "body": "D3: B", "url": "u2"},  # not the owner
        {"author": "owner", "body": "> D3: B\nD1: B, changed my mind\nD9: X", "url": "u3"},
        {"author": "owner", "body": SUMMARY_MARKER + "\nD3: A", "url": "u4"},  # our own summary
    ]
    found = answers(comments, "owner", known)
    assert {c: a["answer"] for c, a in found.items()} == {
        "D1": "B, changed my mind",
        "D2": "as above",
    }
    text = summary(known, found)
    assert '<!-- decisions {"D1": "B, changed my mind", "D2": "as above"} -->' in text
    assert "Still open: D3." in text
    complete = answers(
        comments + [{"author": "owner", "body": "D3: A", "url": "u5"}], "owner", known
    )
    assert "All decisions are in." in summary(known, complete)
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
