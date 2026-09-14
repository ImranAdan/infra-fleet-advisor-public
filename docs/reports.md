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
`advisory/latest` branch for human review.

```bash
gh workflow run fleet-advisory.yml \
  --repo ImranAdan/infra-fleet-advisor-public \
  -f target_ref=main -f synthesizer=stub
```

## Configure report PR delivery

To trigger quality checks automatically on report PRs, configure the optional
advisor-only delivery App with `ADVISOR_REPORT_APP_CLIENT_ID` and
`ADVISOR_REPORT_APP_PRIVATE_KEY`. Without it, delivery uses `GITHUB_TOKEN`, whose
PR events do not start ordinary PR checks. Earlier workflow decline decisions
remain valid when switching to App delivery.

Install the delivery App only on the advisor, with repository
`Contents: Read and write` and `Pull requests: Read and write`. Configure both
App secrets or neither. The workflow restricts its installation token to this
repository and these two permissions, and uses it only for report delivery.
Collectors and the fleet checkout do not receive this token.

Verify an App installation by observing Quality checks on a generated report
PR. The deterministic local suite does not exercise that live GitHub event path.
Do not remove required checks to make a report mergeable. Feedback policy PRs
still use `GITHUB_TOKEN` and retain the check-trigger limitation.

## Review and approve

Inspect provenance, evidence, impact, suggested changes, trade-offs and coverage.
Obtain the required Quality checks. A report proposal changes only
`reports/report.json` and `reports/report.md`; implementation and documentation
changes belong in separate PRs.

Merging the report-only PR approves eligible fleet issue creation and advances
the report baseline. Closing it without merging declines that material report.
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
| Report PR has no Quality checks | Default-token delivery does not start ordinary PR checks; use reviewed maintainer delivery or configure the advisor-only App. |
| Synthesis failed | The run exits non-zero without writing a report; inspect the bounded failure reason. |
| Report merged but no fleet issue | Check the [publisher guide](fleet-publication.md) for enablement, eligibility, freshness and retry. |
