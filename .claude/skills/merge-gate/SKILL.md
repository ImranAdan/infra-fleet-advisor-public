---
name: merge-gate
description: Decide whether an agent may merge a pull request without a human reading it. Runs merge_ready.py, which verifies exact-head CI, advisor evidence, review replies and owner-only scope. Use before merging any pull request you raised.
---

# Merge gate

An agent may merge its own pull request unread only when evidence, not
confidence, says it is safe. This skill makes that decision a command:

```bash
python3 .claude/skills/merge-gate/merge_ready.py <PR_NUMBER>
```

When that command reports `READY`, merge through the same gate so GitHub binds
the operation to the head commit that was checked:

```bash
python3 .claude/skills/merge-gate/merge_ready.py <PR_NUMBER> --merge
```

Same-repository PRs containing `<!-- autonomous-merge -->` may leave this step
to `.github/workflows/autonomous-merge.yml`. The trusted default-branch worker
runs the same command; it cannot convert `PARK`, `JUDGE` or `BLOCKED` into a
merge. Remove the marker to hold the PR open.

| Verdict | Exit | Meaning | What to do |
|---|---|---|---|
| `READY` | 0 | Every condition and applicable decision holds | Rerun with `--merge`, then say what merged and why |
| `PARK` | 10 | An owner-only category needs current-head owner approval | Leave it open and tell the owner the category |
| `JUDGE` | 11 | The independent judge has not approved this head | Wait for its comment, then run the gate again |
| `BLOCKED` | 1 | Evidence, CI, review or the judge blocks it | Fix the reasons, push, run the gate again |

## What it checks

- **Checks:** every check run and status on the head commit completed green.
  One still running is not green.
- **Advisor evidence:** one configured `Advisor Gates` check must complete
  successfully on this head under GitHub Actions. That job contains the drills,
  ratchet, workflow lint and security scan, and its Actions run must come from
  the exact workflow recorded in `decision-policy.toml`. The standard and
  exact-head dispatched report variants are accepted only with their configured
  event and branch provenance; a missing, skipped or same-name check from
  another workflow does not count.
- **Dependency evidence:** remote actions need a full commit SHA, container
  bases need a fixed tag or digest, requirements need exact pins, and changed
  manifests need their sibling lockfiles.
- **Mergeable:** GitHub reports the branch `CLEAN`: no conflicts, not behind.
- **Exact head:** `--merge` passes the checked SHA to GitHub's
  `--match-head-commit`; a concurrent push makes the merge fail and requires a
  new gate run.
- **Review:** no unresolved thread. A thread resolved without a reply saying
  what changed or why a finding was declined surfaces.
- **Evidence:** the body has a `## Verification` section with at least one
  line of the form `` `command` → result``: what was run and what it showed (see the pull request template and
  the Verification section of `AGENTS.md`).
- **Scope:** changes the policy assigns to evidence or the owner, found in the diff: a workflow
  permission or `write` scope, a new `secrets.` reference, a remote action, a
  base image, a chart or dependency version, a dependency manifest, IAM,
  permanent infrastructure, migration, intent, policy, a decision record or
  product requirements. Gate-producing files are merge authority and always
  park for the owner.

## What it cannot check

Judge these yourself. Any one means `PARK`, whatever the script says:

- you disagree with a review finding, in whole or in part;
- the change goes beyond what the owner asked for;
- it is a security finding where merging means judging your own work;
- a check failed and the fix was not obvious.

Encode a recurring judgment as a new rule in `merge_ready.py` with a case in
its self-test (`python3 .claude/skills/merge-gate/merge_ready.py --self-test`), not as more prose here.

An agent never adds `owner-approved` and never posts or imitates a
`github-actions[bot]` judge comment. On `PARK`, the trusted default-branch
worker applies `needs-decision` and posts one explanation bound to the current
head. The owner replies `/approve <full-head-sha>`, which wakes that worker
through a small handoff on GitHub's default-branch
[`issue_comment`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment)
event. The handoff only dispatches the worker; the gate accepts that exact
command only from the repository owner and
only after every check run on the head had started. For compatibility, an
`owner-approved` label under the same timing rule is also accepted by the
scheduled recovery run. Evidence-decided categories need no comment or model: all checks must be
green and the required advisor check must have trusted exact-head provenance.
Workflow-dispatch evidence is also bound to its registered generated head
branch; a successful run from an ordinary feature branch is not evidence.
The optional Anthropic model path in `judge.py` has no trigger: its
`pull_request_target` workflow was removed before GitHub's 2026-11-02 default
block. A future policy category that names the `judge` decider must first give
it a trusted default-branch trigger. Declared intent and the ratchet remain the first
authority, so neither evidence nor a judge approval can override them.
