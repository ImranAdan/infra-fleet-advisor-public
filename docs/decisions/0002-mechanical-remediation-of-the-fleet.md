# PDR 0002: Mechanical remediation of the fleet

- Status: accepted
- Date: 2026-08-28
- Supersedes: the "no pull requests against the fleet" non-goal, and part of
  delivery phase 3, in `docs/product-requirements.md`

## Context

Until now the advisor was read-only with respect to the fleet in the strongest
sense: it cloned, analyzed, and wrote nothing back. Every document said so —
`README.md`, `AGENTS.md`, and `docs/product-requirements.md`, where automated
pull requests against the fleet were both an explicit non-goal and a post-MVP
delivery phase.

The owner asked to see the loop close end to end, choosing this over raising
issues (PDR 0001 D2) with the boundary conflict stated up front. This record
exists so the reversal is a decision rather than a contradiction.

## Decision

The advisor may open a pull request against `infra-fleet-public` proposing a
mechanical fix, under the constraints below. It still may not merge one, and
nothing is applied to the fleet without a human merging it there.

### The report is the only authority

A patch is derived from a published recommendation and the evidence that
recommendation cites. Nothing is discovered by scanning the fleet. Two
consequences:

- a finding that failed validation can never produce a patch, because it was
  never published;
- a file containing the same pattern but never cited as evidence is out of
  bounds. There is a test for exactly this.

Since the source is the *merged* report on the default branch, a human has
already accepted the finding before any patch derived from it can exist.

### Only concerns with no judgement in them

`PATCHERS` in `scenarios/fleet_repository_review/remediation.py` currently holds
one entry: `trivy_ignore_unfixed`, which deletes an `ignore-unfixed: true` line.

`wildcard_iam_permissions` is deliberately absent and should stay absent.
Scoping a wildcard IAM policy requires knowing which API calls a pipeline
actually makes; that is CloudTrail analysis or iteration, not a text transform.
A confident wrong answer there is a security regression.

This inverts the obvious intuition about value: the concern that is easy to patch
is the low-severity one, and the critical finding is precisely the one a machine
must not touch. Adding an entry to `PATCHERS` is a claim that a change is safe
without human judgement, which is rarely true.

### Bounded blast radius

- Manual dispatch only, defaulting to a dry run. Never on a schedule or on merge.
- One workflow (`fleet-remediation.yml`) holds `FLEET_TOKEN`; no other job can
  reach the fleet with write access.
- The token needs contents and pull-requests write on the fleet, and nothing
  else. A GitHub App installation is preferred over a personal access token:
  scoped, rotatable, not tied to a person.
- Patches are idempotent — a re-run over an already-fixed fleet produces no
  change, so a resolved finding is a no-op.
- Evidence paths are validated; a path resolving outside the checkout raises
  rather than being skipped quietly.

### What has not changed

Reviewing is still read-only. The advisory workflow clones the fleet with no
credential beyond public read, and remains a separate workflow. Remediation is
an explicitly invoked act, not a phase of the review.

## Consequences

The strongest version of the read-only promise is gone, and the honest framing is
now narrower: **the advisor never modifies the fleet; it proposes changes a human
merges.** `README.md`, `AGENTS.md`, and `docs/product-requirements.md` are
updated to say that rather than the old absolute.

The risk this accepts is that a mechanical patch is confidently wrong in a
repository the advisor does not own. The mitigations are the evidence boundary,
the deliberately tiny patcher registry, dry-run by default, and a human merge on
the far side. The mitigation that matters most is keeping `PATCHERS` small.
