# Ratchet guard

An advisor change may add proof and findings on an unchanged fleet, never lose
them. The Quality workflow runs this on every advisor pull request.

## Sub-features

- `ratchet-holds` an advisor change keeps every decisive result and check.
- `ratchet-slips` a lost check, lost proof or vanished finding fails with
  exit 8.
- `ratchet-same-fleet` reports of different fleet commits are refused.

## How to get to it (user POV)

- The **Ratchet guard** job in the Quality workflow.
- `scripts/ratchet-guard.sh FLEET BASE_ADVISOR_SHA OUT` locally.

## Driving it with the CLI

Preconditions:

- Doctor clean; the change under test is committed, since the script reviews
  the committed HEAD.

- **Holds.** Run `scripts/ratchet-guard.sh ../infra-fleet-public $(git rev-parse origin/main) $OUT/ratchet`.
  It prints `## Ratchet guard holds` and exits 0.
- **Slips.** On a scratch branch, delete one `- Check:` line from an intent
  file, commit, and run the same command. It prints `## Ratchet guard slipped`,
  names the position under `Lost checks`, and exits 8. Delete the scratch
  branch afterwards.
- **Proof.** Keep both summaries and exit codes.

## Gotchas

- A slip can be right, for example fixing a false positive. The pull request
  must say why.
- The base advisor runs from a temporary worktree at `BASE_ADVISOR_SHA`.
