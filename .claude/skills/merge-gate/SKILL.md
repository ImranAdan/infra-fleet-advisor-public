---
name: merge-gate
description: Decide whether an agent may merge a pull request without a human reading it. Runs merge_ready.py, which checks CI, review replies and verification evidence, then routes scoped decisions to the independent judge or owner policy. Use before merging any pull request you raised.
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

| Verdict | Exit | Meaning | What to do |
|---|---|---|---|
| `READY` | 0 | Every condition and applicable decision holds | Rerun with `--merge`, then say what merged and why |
| `PARK` | 10 | An owner-only category needs current-head owner approval | Leave it open and tell the owner the category |
| `JUDGE` | 11 | The independent judge has not approved this head | Wait for its comment, then run the gate again |
| `BLOCKED` | 1 | Evidence, CI, review or the judge blocks it | Fix the reasons, push, run the gate again |

## What it checks

- **Checks:** every check run and status on the head commit completed green.
  One still running is not green.
- **Mergeable:** GitHub reports the branch `CLEAN`: no conflicts, not behind.
- **Exact head:** `--merge` passes the checked SHA to GitHub's
  `--match-head-commit`; a concurrent push makes the merge fail and requires a
  new gate run.
- **Review:** no unresolved thread. A thread resolved without a reply saying
  what changed or why a finding was declined surfaces.
- **Evidence:** the body has a `## Verification` section with at least one
  line of the form `` `command` → result``: what was run and what it showed (see the pull request template and
  the Verification section of `AGENTS.md`).
- **Scope:** changes a human must decide, found in the diff: a workflow
  permission or `write` scope, a new `secrets.` reference, a remote action, a
  base image, a chart or dependency version, a dependency manifest, IAM,
  permanent infrastructure, intent, policy, a decision record or product
  requirements.

## What it cannot check

Judge these yourself. Any one means `PARK`, whatever the script says:

- you disagree with a review finding, in whole or in part;
- the change goes beyond what the owner asked for;
- it is a security finding where merging means judging your own work;
- a check failed and the fix was not obvious.

Encode a recurring judgment as a new rule in `merge_ready.py` with a case in
its self-test (`python3 .claude/skills/merge-gate/merge_ready.py --self-test`), not as more prose here.

An agent never adds `owner-approved` and never posts or imitates a
`github-actions[bot]` judge comment. When the repository owner adds the label,
the workflow records a trusted approval for that exact head SHA; the gate
requires both records. Judge decisions are bound to the current head SHA too.
The secret-backed judge runs only for branches in this repository, so a fork
pull request stays at `JUDGE` for human handling. Declared intent and its
advisor gate remain the first authority; the judge handles only reversible
categories that policy assigns to it.
