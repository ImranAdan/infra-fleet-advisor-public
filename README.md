# Infra Fleet Advisor

Infra Fleet Advisor is a read-only advisor for the
[`infra-fleet-public`](https://github.com/ImranAdan/infra-fleet-public) GitOps
platform.

It periodically inspects the repository at an immutable Git revision, combines
deterministic evidence with bounded AI analysis, and produces a small,
prioritized set of actionable recommendations for keeping the fleet secure,
reliable, current, maintainable, and cost-conscious.

## Product promise

> Turn the desired state and existing validation signals of one GitOps fleet
> into a trustworthy, evidence-backed improvement backlog.

The advisor does not claim that there is one universally optimal platform
configuration. Recommendations are evaluated against the owner's declared
priorities and accepted trade-offs.

## MVP

The first version will:

- review only `infra-fleet-public`;
- analyze a complete repository snapshot identified by a full Git commit SHA;
- run without AWS or Kubernetes credentials;
- reuse deterministic findings from repository-aware collectors;
- use AI only to synthesize, connect, and explain captured evidence;
- return at most a configured number of ranked recommendations;
- produce both a human-readable Markdown report and structured JSON;
- track recommendations as new, unchanged, resolved, or suppressed across
  runs; and
- remain read-only with respect to fleet code and runtime infrastructure.

The MVP will not modify infrastructure, merge anything, inspect a live cluster,
support arbitrary repositories, or implement autonomous remediation. Reports are
proposed as pull requests in *this* repository.

Reviewing the fleet is read-only. Separately, a manually dispatched workflow may
**propose** a mechanical fix as a pull request against the fleet — never merge
one — for the narrow set of concerns fixable without judgement. See
[PDR 0002](docs/decisions/0002-mechanical-remediation-of-the-fleet.md).

After an advisory report is merged, a separate issues-only workflow can publish
each active recommendation to the fleet as a deduplicated issue. It never
changes issue state; when evidence disappears it adds a note and leaves closure
to a maintainer. See
[PDR 0001](docs/decisions/0001-advisory-delivery-and-feedback-loop.md).

## Review flow

```text
load policy and source revision
              ↓
capture repository evidence
              ↓
run deterministic collectors
              ↓
synthesize bounded recommendations
              ↓
validate evidence and safety rules
              ↓
fingerprint, compare, rank, and report
```

Every recommendation must identify concrete evidence, expected impact,
trade-offs, and confidence. Unsupported model output is rejected rather than
published.

## Usage

```bash
export ANTHROPIC_API_KEY=...   # required by the default --synthesizer anthropic

uv run infra-fleet-advisor review \
  --checkout ../infra-fleet-public \
  --sha <full-40-char-commit-sha> \
  --policy path/to/policy.yaml \
  --output-dir ./review-output \
  --prior-report ./previous-run/report.json   # optional, enables lifecycle tracking
```

`--synthesizer stub` swaps the model for a deterministic table-driven
stand-in, which needs no API key and is what the test suite runs on.

### As a GitHub Actions workflow

`.github/workflows/fleet-advisory.yml` runs the same review on demand
(**Actions → Fleet advisory report → Run workflow**) and proposes the result as
a pull request on the `advisory/latest` branch. It needs an `ANTHROPIC_API_KEY`
repository secret; pick the `stub` synthesizer to dry-run it without one.

The committed `reports/report.json` is the prior report the next run compares
against, which is why it is tracked rather than ignored. Lifecycle therefore
advances only when an advisory pull request is **merged** — an open, unmerged
report is not yet the baseline.

A run opens no pull request only when *every* compared field is unchanged:
findings, cited evidence, collector coverage, and rejection reasons. A change in
any one of them proposes a report — so a run whose accepted findings are
identical but whose rejections differ still opens one.

That comparison deliberately ignores file contents. Every report carries a fresh
run timestamp, and a finding legitimately moves from `new` to `unchanged` on the
next run over an identical fleet, so a plain diff is never empty.

Reports also record *why* candidates were refused, not just how many. A
synthesizer that starts rejecting candidates has drifted, and that is the case
the rejection comparison exists to surface.

Closing an advisory pull request without merging declines that exact material
report state. The workflow records a versioned signature in the pull-request
body and does not re-propose the same findings, evidence, coverage, rejection
reasons, accepted trade-offs, and policy version until one of them changes. It
selects the latest workflow-authored decision from a bounded, complete branch
history, so a newer human-authored pull request cannot hide an earlier workflow
decision. It never interprets pull-request prose as policy or evidence.

If synthesis fails, the run exits non-zero and writes no report. It never
degrades to an empty result, because an empty result would mark every
outstanding finding resolved.

### Publishing accepted recommendations as fleet issues

`.github/workflows/fleet-issues.yml` runs when a merged commit changes
`reports/report.json`, and can also be manually retried. Before any external
write it reloads the report under the current policy and validates source
identity, policy version, fingerprints, evidence support, paths, secret safety,
suppression, accepted trade-offs, and hard output limits.

Configure a GitHub App installed only on `infra-fleet-public`, with repository
`Issues: Read and write` and no contents or pull-request permission. Store its
client ID as `FLEET_ISSUES_APP_CLIENT_ID` and private key as
`FLEET_ISSUES_APP_PRIVATE_KEY` in this repository. The generated installation
token is scoped again in the workflow to that one repository and
`issues: write`.

Each issue carries an `advisor:fp:<digest>` label and an inert fingerprint
marker. Retries check both identities before every create, so a failure after
five of eight issues continues with the remaining three. Existing closed issues
remain closed, active issues remain open, and each fingerprint receives at most
one resolution note; issue prose never enters the advisor.

### Recording a fleet decision in policy

To decline an advisor issue as an accepted trade-off, a maintainer closes the
issue and applies `advisor:wontfix` plus exactly one reason label:

- `advisor:tradeoff:availability`
- `advisor:tradeoff:compatibility`
- `advisor:tradeoff:complexity`
- `advisor:tradeoff:cost`
- `advisor:tradeoff:risk-accepted`

`.github/workflows/fleet-feedback.yml` checks those decisions daily at 05:17 UTC
and can be run manually. Its fleet token is restricted to `issues: read`. The
adapter retains only issue number, state, workflow-App author, and labels; it
does not read issue title, body, or comments.

A decision is eligible only for an issue created by the configured App, with
one valid fingerprint that still maps to one active recommendation. Because
policy accepts trade-offs at concern level, feedback fails safely if multiple
active findings share that concern. Eligible decisions produce a pull request
in this repository that changes only `policy.yaml` and assigns the changed
policy a deterministic new version. A maintainer must merge it. Closing the
pull request declines that exact feedback plan across intervening proposals.
The workflow reads up to 199 branch-history records and fails closed rather than
forgetting a decision if that bound is exceeded.

If the issue is reopened or either decision label is removed before merge, the
workflow withdraws its own stale policy pull request. That automated closure is
marked as a cancellation and does not count as a maintainer declining the plan.
If a push succeeds but pull-request creation fails, the next run can reclaim the
reserved `advisor/feedback-wontfix` branch only after proving it is a
single-parent commit from merged history that changes only `policy.yaml`.

After a feedback policy is merged, this job waits for an advisory report made
under the new policy version. That report keeps the finding visible with the
accepted rationale while making it ineligible for issue publication and
mechanical remediation.

### Proposing a fix to the fleet

```bash
uv run infra-fleet-advisor remediate \
  --checkout ../infra-fleet-public \
  --report reports/report.json \
  --dry-run
```

Applies only what a merged report already justified, to only the files that
report cited as evidence. A file containing the same pattern but never cited is
out of bounds, and re-running over an already-fixed fleet changes nothing.

`.github/workflows/fleet-remediation.yml` does the same in CI and opens the pull
request against the fleet. It needs a `FLEET_TOKEN` secret with contents and
pull-requests write there — a GitHub App installation rather than a personal
token — and defaults to a dry run.

Only `trivy_ignore_unfixed` is patchable today. `wildcard_iam_permissions` is
deliberately excluded: scoping it requires knowing which API calls the pipeline
makes, and a confident wrong answer is a security regression.

## Development

```bash
make setup      # sync the locked environment
make check      # lint, strict typing, and the full test suite
```

`.github/workflows/quality.yml` runs the same gates on every pull request, plus
`gitlint` over commit messages, `actionlint` over the workflows, and a Trivy
filesystem scan. `tests/fixtures` is excluded from that scan: it holds
deliberately insecure Terraform, because that is what the collectors are tested
against.

Tests are deterministic and offline — no network, cloud credentials, or cluster.
The Anthropic synthesizer is exercised through recorded responses.

## Status

The `fleet_repository_review` scenario runs end to end: two deterministic
collectors (GitHub Actions workflows, Terraform IAM policies) feeding synthesis,
validation, and lifecycle tracking.

The Anthropic synthesizer is implemented and unit-tested against recorded
responses, but **has never been run against the live API**. Every report produced
so far used `--synthesizer stub`, so the findings are real — the collectors are
deterministic — while the prose around them is templated.

`docs/decisions/0001-advisory-delivery-and-feedback-loop.md` records what closing
the loop requires. Stable evidence identity, closed-pull-request decline
records, deduplicated fleet issue publication, and label-only `wontfix`
feedback into human-reviewed policy are implemented.

## Documentation

- [Product research](docs/product-research.md)
- [Product requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [PDR 0001: Advisory delivery and the fleet feedback loop](docs/decisions/0001-advisory-delivery-and-feedback-loop.md)
- [PDR 0002: Mechanical remediation of the fleet](docs/decisions/0002-mechanical-remediation-of-the-fleet.md)
- [Repository guidance](AGENTS.md)

## License

MIT
