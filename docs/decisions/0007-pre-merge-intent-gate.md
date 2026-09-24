# PDR 0007: Pre-merge intent gate

- Status: accepted
- Date: 2026-09-24
- Extends: PDR 0003 intent compilation and divergence delivery

## Owner decision

The nightly loop finds a divergence only after it reaches fleet `main`, then
spends a report, an issue and a fix PR undoing it. The owner wants the same
deterministic evaluation to run on fleet pull requests, so a change that would
break a declared position is seen before it merges.

## Decision

1. The advisor ships a composite action, `.github/actions/intent-gate`. The
   fleet calls it from its own pull-request workflow, pinned by commit SHA, so
   an advisor upgrade reaches the fleet only as an ordinary, reviewed fleet
   change. Dependabot can automate that once the advisor publishes release
   tags; until then the pin is bumped by hand.
2. The action reviews the pull request's merge commit and its first parent (the
   base as it would be merged) with the `stub`
   synthesizer and the advisor's own policy and intent, then `gate` compares
   the two reports. It fails when a position that was not divergent on the
   base is divergent on the head, and when a position with a decisive result
   on the base (satisfied or divergent) becomes unevaluable on the head: a
   change must not hide a divergence by making a collector incomplete. Only a
   move from divergent to satisfied counts as resolved. Pre-existing
   divergences and lost collector coverage are reported without failing.
3. The gate is read-only: the workflow holds `contents: read`, creates no
   issue, comment, report PR or label, calls no model, and never applies
   anything. Its verdict is the check status and its explanation is the job
   summary.
4. The nightly report remains the decision record for fleet issues (PDR 0006).
   The gate prevents new divergence; it does not publish or resolve work.

## Consequences

- Advisor code, policy and intent now execute in fleet CI. The SHA pin and the
  read-only token bound that: a compromised advisor commit can fail or pass a
  check, not change the fleet.
- A pull request that deliberately accepts a divergence needs an owner-approved
  intent or policy change in this repository first, or a maintainer override of
  the failing check. The gate does not weaken intent to let a change through.
- Checks that are divergence-only still gate: a new divergence is evidence.
  Positions without a check cannot gate, which keeps coverage work valuable.
