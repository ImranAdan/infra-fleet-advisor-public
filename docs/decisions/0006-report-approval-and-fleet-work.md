# PDR 0006: Report approval and fleet work

- Status: accepted
- Date: 2026-09-14
- Supersedes: PDR 0004 automatic advisor capability-ticket publication
- Refines: PDR 0001 advisory delivery and issue creation

## Owner decision

The owner wants the advisor to propose a report PR containing recommendations.
A reviewer examines it and decides whether to merge it. That PR is the decision
record for a separate workflow to create applicable issues in
`infra-fleet-public`. The owner then selects valuable fleet issues and asks an
agent working in that repository to propose PR fixes.

Creating advisor tickets for every unsupported intent generated development
backlog instead of delivering this workflow. It is not the requested product.

## Decision

1. A merged report-only PR is the issue-creation decision record. Its JSON and
   Markdown are the reviewed artifact. A declined PR, direct report push or
   advisor implementation PR does not authorize fleet issue creation.
2. The separate publisher runs after a report PR merges. It verifies bounded
   GitHub API metadata and the report-only file set, then materializes the exact
   merge commit's report using trusted default-branch advisor code. It checks
   that this remains the current merged report and matches current policy and
   intent before the existing full eligibility validation.
3. Every new fleet issue links to the approving report PR and approved report
   commit. It contains repository evidence, expected impact, suggested change,
   trade-offs and confidence. Merge approves publication of eligible findings;
   selecting them for implementation is a later maintainer decision.
4. Incomplete relevant collection defers publication, including recommendations
   carried forward from historical evidence. Those records remain visible in
   the report; uncertainty does not create a new fix request or resolution.
   This conservative MVP gate also waits on findings in a partially collected
   surface until that surface is complete.
5. Issue retries specify the merged report PR number. A superseded report cannot
   replay. Fingerprint deduplication remains per action, so a partial publication
   run can be retried without duplicating completed creates.
6. Unsupported intent stays in report evaluation and coverage. Remove the
   automatic advisor issue workflow and its publication CLI. Keep the existing
   coverage gaps in a linked review snapshot and close generated tickets as
   superseded, without claiming those checks were implemented.
7. The fleet publisher uses the existing issues-only App installation. Its
   `FLEET_ISSUES_ENABLED=true` configuration enables this handoff. Optional
   feedback uses its separate `FLEET_FEEDBACK_ENABLED=true` setting; enabling
   issue publication does not start feedback or an implementation agent.

The merge trigger uses `pull_request_target: closed` with a merged condition,
following GitHub's [merge event guidance](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#running-your-pull_request_target-workflow-when-a-pull-request-merges).
Only default-branch code is checked out; no PR-head code is executed. PR prose
is inert, and the fleet App token remains limited to issue writes.

## Consequences

The ordinary work queue is in the fleet. There is no automatic fixing agent,
fleet merge, deployment or issue closure. The owner requests agent work on
chosen issues and reviews its proposed PRs. A later advisor run evaluates the
resulting repository state; absence of detection is still not proof that a
broader risk has disappeared.

Repeated material results create no new report PR. Repeated approved findings
reuse existing issue identities. Unsupported positions remain visible without
automatically expanding an advisor backlog. The optional offline
`capability-plan` diagnostic and legacy library tests remain available; there
is no supported CLI or workflow for publishing advisor capability tickets.

See [the operating workflow](../WORKFLOW.md) and
[the historical coverage review](../COVERAGE-REVIEW.md).
