# Setup and integration

Infra Fleet is the platform template. Infra Fleet Advisor is the repository
review product. The current supported target is
`ImranAdan/infra-fleet-public`; arbitrary repositories and private fleet targets
are outside the implemented MVP. Changing a checkout path does not configure a
new publication destination. Repository identities are deliberately checked in
trusted code and workflows.

## Local review

Clone the advisor and fleet alongside each other, then run `make setup` and
`make review` in the advisor. `make setup` installs the locked environment and
fails if `uv.lock` is stale. `make review` uses `stub`, resolves the fleet's full
HEAD SHA, verifies a clean checkout, and writes JSON and Markdown under
`review-output/` without touching either the fleet or the committed report.

Supply `FLEET_CHECKOUT` and `REVIEW_OUTPUT` to Make to change these locations.
The output must stay outside the fleet checkout, including through symlinks.
The initial install needs internet access. Review then evaluates local
repository files through the deterministic stub and registered collectors.

For lifecycle comparison, run the CLI with explicit inputs and
`--prior-report /path/to/previous/report.json`. A local prior report is for
experimentation; automation consumes only the report merged in advisor `main`.

## Automation and credentials

| Path | Default | Configuration | Effect |
|---|---|---|---|
| Local `make review` | Available | Clean fleet checkout | Local report only |
| Fleet advisory workflow | Automatic deterministic reviews; manual default is `stub` | Actions allowed to create PRs; optional report delivery App below | Proposes a report in the advisor |
| Manual `anthropic` review | Explicit opt-in | `ANTHROPIC_API_KEY` | One bounded model invocation for wording |
| Fleet issue publication | Disabled | `FLEET_ISSUES_ENABLED=true`, `FLEET_ISSUES_APP_CLIENT_ID`, `FLEET_ISSUES_APP_PRIVATE_KEY` | Deduplicated fleet issues |
| Fleet decision feedback | Disabled | `FLEET_FEEDBACK_ENABLED=true` and the issues App credentials; token downscoped to `issues: read` | Proposes policy in the advisor |
| Remediation dry run | Manual; `dry_run=true` | Current ratified report and public fleet read | Patch preview only |
| Remediation proposal | Manual; `dry_run=false` | Above plus `FLEET_TOKEN` with fleet contents and PR write | Proposes a fleet PR |

Do not grant the issues App contents or pull-request permissions. Install it
only on the fleet. Its short-lived issue token is restricted again by the
workflow. The separate remediation credential must never be used for analysis,
issue publication, or feedback. No path merges a fleet proposal or touches AWS.

Set `FLEET_ISSUES_ENABLED=true` to enable the approved-report fleet handoff.
Optional decision feedback has a separate `FLEET_FEEDBACK_ENABLED=true` opt-in.
Enabling fleet issue publication does not enable feedback or start a fixing agent.
An enabled publisher with missing credentials fails with the missing names.

## Approval and report freshness

The advisory workflow proposes `reports/report.json` and `reports/report.md` on
`advisory/latest`. Review and merge that proposal to advance the baseline.
Closing it without merging declines that exact material report state.

The report-only PR is the decision record for fleet issue creation. The
publisher verifies the merged PR and links every issue to it. Retry with its PR
number through the workflow `report_pr` input; a superseded report cannot replay.
Recommendations with incomplete relevant collection are deferred. Unverified
positions stay in report coverage, not an automatically generated advisor
backlog. See [PDR 0006](decisions/0006-report-approval-and-fleet-work.md).

Intent changes often merge before a report reflects them. Fleet publication
waits for matching policy version and intent digest. They
never regenerate an unapproved report inside the publication workflow. A
missing report also waits; malformed provenance or the wrong fleet identity
fails. A current report still passes the existing full publication validation.

Without additional configuration, the workflow creates report PRs using
`GITHUB_TOKEN`. GitHub does not trigger ordinary `pull_request` quality workflows
from those token-authored PRs, so required checks can block a report merge even
when analysis succeeds. The workflow records that limitation in its summary.

For report PRs that trigger quality checks, create a separate GitHub App installed
only on the advisor, with repository `Contents: Read and write` and
`Pull requests: Read and write`. Store its client ID as
`ADVISOR_REPORT_APP_CLIENT_ID` and private key as `ADVISOR_REPORT_APP_PRIVATE_KEY`
in the advisor repository. Configure both or neither. The workflow restricts
its generated installation token to this advisor repository and these two
permissions, then uses it only for report delivery. It never gives it to the
fleet checkout, collectors, issue publisher, or remediation.

Decline history accepts the configured delivery App and the earlier
`github-actions[bot]` records. Other authors cannot hide a decision. A new App
installation must be verified by observing quality checks on a generated report
PR; this local audit has not minted a token or exercised that GitHub event path.
Do not remove required checks to make a report mergeable. Feedback policy PRs
still use `GITHUB_TOKEN` and retain this check-trigger limitation.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| `dirty_checkout` | Commit or move local/untracked changes, or use a separate clean clone. Ignored files are never evidence. |
| `sha_mismatch` | Review the declared full commit in a clean checkout; do not substitute stale report evidence. |
| `unsafe output error` | Put output outside the fleet checkout. |
| `policy_changed` or `intent_changed` readiness | Wait for a report under the current versions to be merged. |
| `report_missing` readiness | Run the advisory report path and ratify its first report. |
| No API key | Use the default `stub`; `anthropic` requires explicit configuration. |
| Fleet issue job skipped | Configure the issues App and `FLEET_ISSUES_ENABLED=true`; automatic publication requires a merged report PR. |
| Feedback job skipped | Optional feedback requires its separate `FLEET_FEEDBACK_ENABLED=true` setting. |
| No mechanically fixable findings | Expected when no ratified active concern has a registered patcher; only `trivy_ignore_unfixed` is patchable today. |

## What a successful review proves

The review captures desired state from one Git commit. It does not establish
that a private deployment matches that state or that live infrastructure is
healthy. Three collectors inspect workflow settings, Terraform IAM policy
statements, and raw Kubernetes Deployments. Seventeen positions are declared;
only three currently have registered checks. Unsupported positions remain
explicit gaps. A clean report is not full platform certification.

The rollout collector also sees Flux's generated `source-controller` Deployment,
whose upstream strategy is `Recreate`. Treat that recommendation as a question
about the intent's workload scope and accepted availability trade-off. Do not
mechanically rewrite generated upstream controller manifests to satisfy a
generic application rollout rule.

Terraform's downloaded `.terraform` module files are excluded from analysis
unless deliberately tracked. Workflow and Terraform collectors filter policy
exclusions and untracked paths before applying the source-file budget. The IAM
parser handles bounded literal `jsonencode` policy objects, including quoted
HCL condition keys. Local references, interpolated strings, externally supplied
policies, and unsupported policy shapes produce partial coverage. In particular,
the fleet's load balancer controller references an HTTP policy response that the
advisor does not fetch. That missing policy remains a coverage gap even when
other policies produce concrete findings. The wildcard check does not evaluate
effective permissions after conditions and denies.
