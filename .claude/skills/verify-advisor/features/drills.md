# Check drills

Every registered check has a drill: one literal violation of the real fleet,
applied in a throwaway worktree, that must make its position diverge. A check
that stops seeing the fleet goes red instead of inflating coverage.

## Sub-features

- `drill-caught` each drill makes its position diverge.
- `drill-stale` a drill whose text the fleet no longer contains is reported as
  stale, not passed.
- `drill-per-check` every registered check has at least one drill.

## How to get to it (user POV)

- The **Check drills** job in the Quality workflow and the nightly report.
- `uv run --frozen infra-fleet-advisor drill …` locally.

## Driving it with the CLI

Preconditions:

- Doctor clean; the fleet checkout is at the commit to prove against,
  usually `origin/main`.

- **All drills.** Run `uv run --frozen infra-fleet-advisor drill --checkout ../infra-fleet-public --drills drills/fleet-mutations.yaml --policy policy.yaml --intent-dir intent --output-dir $OUT/drills`.
  The table lists every drill as `caught` or `already divergent on the fleet`,
  and the command exits 0.
- **One check.** Write a drills file holding only that proposition's entries
  and run the same command with it. Use this after changing one collector.
- **Proof.** Keep the drill table and each drill's `report.json`.

## Gotchas

- `find` is literal text and every occurrence is replaced; a drill goes stale
  when the fleet rewrites that text. Update the drill in the same change.
- `already divergent` proves nothing about that check; the fleet already
  violates it.
