# Report automation and review

[Documentation index](README.md)

## Run a report

`.github/workflows/fleet-advisory.yml` runs the same review after merged intent,
policy, dependency, or advisor implementation changes and once daily at 04:23
UTC, using the deterministic `stub` synthesizer. The schedule provides bounded
polling for changes to fleet `main`; unchanged material produces no pull request.
The workflow can also be run on demand (**Actions → Fleet advisory report → Run
workflow**) with either `stub` or `anthropic`. Only a manual `anthropic` run needs
the `ANTHROPIC_API_KEY` repository secret. Changed output is proposed on the
`advisory/latest` branch for the exact-head autonomous gate.

```bash
gh workflow run fleet-advisory.yml \
  --repo ImranAdan/infra-fleet-advisor-public \
  -f target_ref=main -f synthesizer=stub
```

## Report PR delivery

Delivery uses the repository's `GITHUB_TOKEN`; no report App or personal token
is required. Bot-authored report-only changes are excluded from the ordinary
`pull_request` trigger because GitHub can leave that run waiting for approval
and block branch protection. The advisory workflow explicitly dispatches
`Quality` on `advisory/latest` and passes the PR number. The read-only Quality
workflow resolves the base, title and exact head from GitHub, then runs the same
commit, test, drill, ratchet, workflow and security jobs as an ordinary PR.

The dispatch is associated with the report branch head, and the merge gate
accepts dispatched ratchet evidence only from `advisory/latest`. The report
workflow waits for its completion before dispatching the autonomous merge
worker. The hourly worker schedule remains a recovery path. Do not remove
required checks to make a report mergeable. The daily publication recovery scans
a bounded report history and selects the latest merge time, so later activity on
an older PR cannot hide the current decision record.

## Automatic merge, hold and decline

Each workflow report includes the autonomous marker and a Verification section.
The default-branch worker merges it only after Quality, the ratchet, every other
head check and the merge gate pass. A report proposal changes only
`reports/report.json` and `reports/report.md`; implementation and documentation
changes belong in separate PRs. Remove the marker to hold it for inspection.

Merging the report-only PR records acceptance by deterministic evidence,
authorizes eligible Fleet issue creation and advances the report baseline.
Closing it without merging declines that material report.
See [fleet publication](fleet-publication.md) for configuration and eligibility,
and the [runbook](WORKFLOW.md) to select fleet issues for an agent afterward.

The committed `reports/report.json` is the prior report the next run compares
against, which is why it is tracked rather than ignored. Lifecycle therefore
advances only when an advisory pull request is **merged** — an open, unmerged
report is not yet the baseline.

## Material changes and decline history

A run opens no pull request only when *every* compared field is unchanged:
findings, cited evidence, collector coverage, and rejection reasons. A change in
any one of them proposes a report — so a run whose accepted findings are
identical but whose rejections differ still opens one.

The material signature ignores timestamp and source-revision changes alone,
and the expected lifecycle move from `new` to `unchanged`. It compares report
meaning rather than a raw file diff, which would change on every run.

Reports also record *why* candidates were refused, not just how many. A
synthesizer that starts rejecting candidates has drifted, and that is the case
the rejection comparison exists to surface.

Closing an advisory pull request without merging declines that exact material
report state. The workflow records a versioned signature in the pull-request
body and does not re-propose the same intent digest, proposition evaluations,
findings, evidence, coverage, rejection reasons, accepted trade-offs, and policy
version until one of them changes. It selects the latest workflow-authored
decision from a bounded, complete branch
history, so a newer human-authored pull request cannot hide an earlier workflow
decision. It never interprets pull-request prose as policy or evidence.

If synthesis fails, the run exits non-zero and writes no report. It never
degrades to an empty result, because an empty result would mark every
outstanding finding resolved.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| No new report PR | Material is unchanged or matches a prior declined workflow report. |
| Report PR has no Quality checks | Inspect the `Fleet advisory report` run's final dispatch and confirm Actions are enabled for the repository. No delivery secret is required. |
| Synthesis failed | The run exits non-zero without writing a report; inspect the bounded failure reason. |
| Report merged but no fleet issue | Check the [publisher guide](fleet-publication.md) for enablement, eligibility, freshness and retry. |
