# Intent gate

A fleet change fails when a declared position newly diverges or loses its
decisive result. The fleet runs this gate on every pull request, pinned to an
advisor commit.

## Sub-features

- `gate-pass` an unchanged or compatible fleet change passes.
- `gate-regression` a newly divergent position fails with exit 6.
- `gate-obscured` a position that loses its decisive result fails too.

## How to get to it (user POV)

- The fleet's **Intent gate / Declared intent** check on each pull request.
- `scripts/intent-gate.sh FLEET BASE_SHA HEAD_SHA OUT` locally.

## Driving it with the CLI

Preconditions:

- Doctor clean; both SHAs exist in the fleet checkout.

- **Pass.** Run `scripts/intent-gate.sh ../infra-fleet-public $(git -C ../infra-fleet-public rev-parse origin/main) <candidate-sha> $OUT/gate`.
  It prints `## Intent gate passes` and exits 0.
- **Regression.** Drive a check's drill (see [drills](drills.md)); the drill's
  report is exactly what the gate would compare, and its position turns
  divergent.
- **Advisor change for the fleet.** Before merging an advisor change that
  alters what it can read (a renderer or collector change), run the gate with
  that advisor on a fleet change that needs it, and bump the fleet's pin after
  merging.
- **Proof.** Keep the gate summary and exit code.

## Gotchas

- The fleet's gate uses the pinned advisor commit, not advisor `main`.
- Reports from different intent catalogs are refused; the gate compares one
  catalog.
