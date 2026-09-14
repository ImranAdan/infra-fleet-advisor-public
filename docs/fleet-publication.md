# Publishing approved recommendations to the fleet

[Documentation index](README.md)

## Approval and eligibility

When `FLEET_ISSUES_ENABLED=true`, `.github/workflows/fleet-issues.yml` runs after
a report-only PR is merged into advisor `main`. Closing an unmerged PR, merging
advisor implementation code, or directly pushing a report does not authorize
issue creation. The workflow verifies the PR and materializes its exact merged
report using trusted default-branch code. A superseded report cannot be replayed.
It reloads the current policy and catalog and validates provenance,
fingerprints, evidence, paths, suppression, accepted trade-offs and hard limits.
Recommendations whose relevant collector is incomplete are deferred, including
historical carry-forwards; uncertainty does not become a fresh fix request.

Live main is re-fetched immediately before acquiring the write token and again
before publication. A changed report, policy, intent or validation input pauses
the write. Fetched code is never executed. This checks freshness without locking
repository merges. Every new issue links to the approving report PR and its
merge commit; see [PDR 0006](decisions/0006-report-approval-and-fleet-work.md).

## Retry the approved report

For a retry, select **Actions → Publish fleet advisory issues → Run workflow**
and supply the merged report PR number, or run:

```bash
gh workflow run fleet-issues.yml \
  --repo ImranAdan/infra-fleet-advisor-public -f report_pr=<merged-report-pr>
```

## Configure the issues App

Configure a GitHub App installed only on `infra-fleet-public`, with repository
`Issues: Read and write` and no contents or pull-request permission. Store its
client ID as `FLEET_ISSUES_APP_CLIENT_ID` and private key as
`FLEET_ISSUES_APP_PRIVATE_KEY` in this repository. The generated installation
token is scoped again in the workflow to that one repository and
`issues: write`. The publisher validates both secrets before requesting a token
and fails with the missing secret names; it never falls back to a personal token
or a broader credential.

Set the repository Actions variable `FLEET_ISSUES_ENABLED` to `true` only after
configuring those App secrets. This enables the fleet handoff after report
approval. Optional decision feedback has its own `FLEET_FEEDBACK_ENABLED=true`
setting and remains disabled unless separately selected. See the
[feedback guide](feedback.md). Publication waits if the merged report uses an
older policy or intent catalog; it resumes after a current report is
merged and still performs the complete validation before writing.

## Deduplication and issue state

Each issue carries an `advisor:fp:<digest>` label and an inert fingerprint
marker. Retries check both identities before every create, so a failure after
five of eight issues continues with the remaining three. Existing closed issues
remain closed, active issues remain open, and each fingerprint receives at most
one resolution note; issue prose never enters the advisor.

Selecting valuable issues for an agent, reviewing fleet fix PRs and deciding
closure remain maintainer actions. Issue creation does not start an agent. The
[runbook](WORKFLOW.md) describes this handoff.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| Publication job skipped | Requires `FLEET_ISSUES_ENABLED=true` and a merged report PR, or a manual retry with its number. |
| Missing credential error | Configure the named issues-App secrets; do not substitute a broader token. |
| `policy_changed` or `intent_changed` | Approve a report under the current versions. |
| `report_missing` | Generate and approve a report first. |
| Superseded report or inputs changed | Review the current report; a stale report cannot authorize new writes. |
| Eligible count is zero or findings deferred | Check suppression, accepted trade-offs and relevant collector coverage in the report. |
