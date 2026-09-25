# Advisor verification map

The maintained index of what the advisor does and what proves each behavior.

## Baseline preconditions

- `make setup` has run and `.claude/skills/verify-advisor/doctor.sh` exits 0.
- The fleet checkout is clean at a known commit; record it. Fetching it needs
  approval (see the skill's Launch).
- `OUT="${TMPDIR:-/tmp}/advisor-verify/$(date -u +%Y%m%dT%H%M%SZ)"`.

## Driving conventions

- One output directory per drive, under `$OUT`, never inside a checkout.
- Treat exit codes as the verdict: 0 ok, 2 policy, 3 provenance, 4 pipeline,
  5 unsafe output, 6 intent regression, 7 drill failed, 8 ratchet slipped.
- Read reports with `summarize.py`, not by eye.

## Proof and skip reporting

- Record the fleet commit, the advisor commit and the exit code.
- For a check, show it passing on the fleet and its drill diverging.
- Report a partial collector as unknown, with its error summary.

## Feature entry contract

Each feature file has an H1, one paragraph, and four H2s in order:
`Sub-features`, `How to get to it (user POV)`, `Driving it with the CLI`,
`Gotchas`.

## Features

- [Review](review.md): one review of the fleet produces an evidenced report.
- [Intent gate](intent-gate.md): a fleet change that newly diverges fails.
- [Ratchet guard](ratchet.md): an advisor change that loses proof fails.
- [Check drills](drills.md): every check fires on a literal violation.
