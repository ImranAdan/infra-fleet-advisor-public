# Review

One review of a clean fleet commit evaluates every declared position and
writes a report whose every claim cites repository evidence.

## Sub-features

- `review-runs` the review completes with exit 0.
- `review-positions` every position has a registered check and a result.
- `review-coverage` every collector reports its coverage.
- `review-provenance` the report names the fleet commit, intent digest and
  collector versions.

## How to get to it (user POV)

- `make review` (defaults to `../infra-fleet-public` at its HEAD).
- The nightly **Fleet advisory report** workflow, which proposes the report as
  a pull request.

## Driving it with the CLI

Preconditions:

- Doctor clean; `$OUT` set.

- **Run.** Run `make review REVIEW_OUTPUT=$OUT/review`. It exits 0 and prints
  `Intent: N of N positions have a check — …`.
- **Summarise.** Run `.claude/skills/verify-advisor/summarize.py $OUT/review/report.json`.
  It prints the fleet commit, the counts, `coverage gaps: 0` and each
  divergent position.
- **Compare with the approved report.** Run
  `.claude/skills/verify-advisor/summarize.py $OUT/review/report.json reports/report.json`.
  Every changed position is explained by a fleet or advisor change since the
  approved report.
- **Proof.** Keep `report.json`, `report.md` and the summary output.

## Gotchas

- A dirty fleet checkout is refused (exit 3); commit or check out a clean ref.
- `reports/report.json` is the last *approved* report and may lag both repos.
- A position that is `declared_unverified` with a coverage gap is unknown, not
  healthy.
