---
name: verify-advisor
description: Drive Infra Fleet Advisor's CLI against a real fleet checkout and capture evidence that a change works - reviews, the intent gate, the ratchet guard and check drills. Use before claiming an advisor change works, when a collector, check, renderer or intent changes, or when a report's numbers look wrong.
---

# Verify the advisor

Prove behavior by running the real CLI against the real fleet, not only unit
fixtures. Unit tests prove a collector parses a fixture; only a review of the
fleet proves it still sees the fleet. Read
[`features/README.md`](features/README.md), then use the matching feature file.

Adapted from the `create-verification-skill` and `maintain-verification-skill`
method in [pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT).

## Launch

```bash
make setup                         # uv sync --frozen
git -C ../infra-fleet-public fetch origin main
```

There is no server. Every drive is one CLI run in its own output directory.
The fleet checkout defaults to `../infra-fleet-public`; the advisor reads it
and never writes to it (the gate, ratchet and drill scripts add temporary
worktrees to its `.git` and remove them).

## Doctor

```bash
.claude/skills/verify-advisor/doctor.sh [FLEET_CHECKOUT]
```

Read-only; exits 1 on any `FAIL`. It checks the locked environment, that the
CLI starts, that the intent catalog loads (and how many positions have a
registered check), and that the fleet checkout is clean, since the advisor
reviews clean commits only.

## Drive

| Surface | Command | Pass |
|---|---|---|
| Review | `make review REVIEW_OUTPUT=$OUT/review` | exit 0; `report.json` written |
| Intent gate | `scripts/intent-gate.sh FLEET BASE_SHA HEAD_SHA $OUT/gate` | exit 0 passes, exit 6 is a regression |
| Ratchet guard | `scripts/ratchet-guard.sh FLEET BASE_ADVISOR_SHA $OUT/ratchet` | exit 0 holds, exit 8 slipped |
| Check drills | `uv run --frozen infra-fleet-advisor drill --checkout FLEET --drills drills/fleet-mutations.yaml --policy policy.yaml --intent-dir intent --output-dir $OUT/drills` | every drill `caught` or `already divergent` |

Read any report with
`.claude/skills/verify-advisor/summarize.py REPORT_JSON [BASE_REPORT_JSON]`.
It prints the reviewed fleet commit, positions by result, coverage gaps and
divergences, and with a base report every position whose result changed.

## Evidence

`OUT="${TMPDIR:-/tmp}/advisor-verify/$(date -u +%Y%m%dT%H%M%SZ)"`, outside both
checkouts; the advisor refuses output inside the fleet. The standard:

- Review the real fleet at a named commit, and record that commit with the
  result.
- Prove a check both ways: it passes on the fleet as it is, and its drill (a
  literal violation) makes it diverge. A check that cannot fail proves nothing.
- Compare against a base: the same fleet commit under the previous advisor
  (ratchet), or the previous fleet commit under the same advisor (gate). Every
  changed position needs an explanation.
- Coverage gaps are results. A partial collector with no divergence is
  "unknown", never "satisfied".
- Say `inconclusive` when a drive could not run.

## Cleanup

Nothing runs in the background. The scripts remove their worktrees on exit;
after an interrupted run, check `git -C ../infra-fleet-public worktree list`
and remove only worktrees under the run's temporary directory. Evidence stays
in `$OUT`.

## Maintain

When a collector, check, intent or CLI command changes, re-drive the affected
feature and update its file in the same change. A periodic pass reads each
feature file against the source, drives every feature once, and ends `clean`,
`changed` (one PR, confined to this directory) or `blocked`. Never edit
product code in that pass; a map that no longer matches is either drift (fix
the map) or a regression (report it).
