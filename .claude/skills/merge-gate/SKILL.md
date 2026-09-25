---
name: merge-gate
description: Decide whether an agent may merge a pull request without a human reading it. Runs merge_ready.py, which turns the merge conditions into checks - green checks on the head commit, every review thread resolved with a reply, a Verification section with evidence, and no permission, credential, dependency or decision-record change. Use before merging any pull request you raised.
---

# Merge gate

An agent may merge its own pull request unread only when evidence, not
confidence, says it is safe. This skill makes that decision a command:

```bash
python3 .claude/skills/merge-gate/merge_ready.py <PR_NUMBER>
```

| Verdict | Exit | Meaning | What to do |
|---|---|---|---|
| `READY` | 0 | Every condition holds | Merge, then say what merged and why |
| `SURFACE` | 10 | Mergeable, but a human decides | Do not merge; tell the owner each reason |
| `BLOCKED` | 1 | Not mergeable yet | Fix the reasons, push, run the gate again |

## What it checks

- **Checks:** every check run and status on the head commit completed green.
  One still running is not green.
- **Mergeable:** GitHub reports the branch `CLEAN`: no conflicts, not behind.
- **Review:** no unresolved thread. A thread resolved without a reply saying
  what changed or why a finding was declined surfaces.
- **Evidence:** the body has a `## Verification` section with at least one
  command: what was run and what it showed (see the pull request template and
  the Verification section of `AGENTS.md`).
- **Scope:** changes a human must decide, found in the diff: a workflow
  permission or `write` scope, a new `secrets.` reference, a remote action, a
  base image, a chart or dependency version, a dependency manifest, IAM,
  permanent infrastructure, intent, policy, a decision record or product
  requirements.

## What it cannot check

Judge these yourself. Any one means `SURFACE`, whatever the script says:

- you disagree with a review finding, in whole or in part;
- the change goes beyond what the owner asked for;
- it is a security finding where merging means judging your own work;
- a check failed and the fix was not obvious.

Encode a recurring judgment as a new rule in `merge_ready.py` with a case in
its self-test (`python3 merge_ready.py --self-test`), not as more prose here.
