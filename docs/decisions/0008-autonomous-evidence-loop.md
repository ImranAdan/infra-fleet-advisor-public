# PDR 0008: Autonomous evidence loop

- Status: accepted
- Date: 2026-09-28
- Supersedes: the manual-merge requirements in PDR 0002 and PDR 0006
- Retains: their evidence, provenance, least-privilege and deduplication boundaries

## Context

The report, issue and remediation boundaries work, but every report and fix
still stops for an owner merge. That makes the owner a queue consumer even when
the advisor, tests and merge gate already have enough evidence to decide. It
contradicts M-005's goal that routine reversible work should proceed without a
paid model or repeated owner intervention.

## Decision

Same-repository PRs opt into an autonomous lane with an inert body marker. A
trusted default-branch worker evaluates each candidate through
`merge_ready.py --merge`. The marker grants no authority: all exact-head checks,
advisor evidence, dependency safeguards, review-thread rules and scope decisions
still apply. `READY` merges. `PARK`, `JUDGE` and `BLOCKED` remain open. Removing
the marker holds a PR. The same trusted worker surfaces `PARK` with a
head-bound `needs-decision` prompt and reruns when the owner replies
`/approve <full-head-sha>`; a small handoff uses GitHub's default-branch
[`issue_comment`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment)
event to dispatch the worker rather than using `pull_request_target`.

Changed report PRs opt in automatically. Their merge remains the immutable
decision record for Fleet issue publication, but the decision is now made by
declared intent plus deterministic exact-head evidence. Closing a report PR
still records a decline of that material signature.

Both generated PR paths use `GITHUB_TOKEN` to create their branches and pull
requests. Token-authored PR delivery cannot rely on a runnable ordinary
pull-request workflow: GitHub may suppress it or hold it for approval. Trusted
default-branch code explicitly dispatches a read-only validation workflow on
the generated branch. The dispatch resolves and checks
the PR's exact base and head before producing evidence. Advisor report-only
changes are excluded from the native Quality trigger so a bot approval request
cannot block branch protection; the report workflow waits for dispatched
Quality, validates the bot author, report-only diff, exact head and both job
results, and relays the two consolidated branch-protection contexts as GitHub
Actions commit statuses linked to that run. It then dispatches the autonomous
merge worker. The worker still reads the underlying Quality check runs,
including the isolated drill and ratchet gate job, before it can merge.

The Fleet worker reads evidence and performs decision handoffs with its bounded
`GITHUB_TOKEN`. It supplies a separate, short-lived GitHub App token only to
the exact-head merge mutation. The token is restricted to the Fleet repository
and requests only Contents write, the permission GitHub's merge endpoint
requires. The workflow token retains Pull requests write for decision comments
but only Contents read, so it cannot merge. An App-authored merge emits
the ordinary `push` event that GitHub suppresses for `GITHUB_TOKEN`, so Release
Please and future post-merge consumers run without individual dispatch
workarounds. The same repository-scoped App credentials support Release Please.
Creating the App, granting its installation permissions and storing its private
key remain one-time owner actions; agents cannot widen this authority.

Registered mechanical remediation moves into the Fleet repository. A read-only
job runs merged Advisor code and exports a patch artifact. A separate Fleet job
applies the patch as data and may open an opted-in PR using Fleet's own
`GITHUB_TOKEN`. Advisor code never receives that token. The Fleet intent gate,
CI and merge gate decide the PR. Concerns without a registered deterministic
patcher remain issues for an external coding agent.

The autonomous worker, its selector, report opt-in, remediation workflow and
patcher registry are merge authority. Changes to them require the owner, as do
credentials, widened permissions, IAM, permanent infrastructure, declared
intent and migrations. This is the bootstrap exception that prevents the
system from expanding its own authority.

## Consequences

The normal loop no longer waits for an owner click: report, issue publication,
registered remediation PR and evidence-approved merge can progress on their own.
The owner is involved only for owner-only scope, a deadlock, or an explicit
hold. General code generation still needs a coding-agent runtime; GitHub Actions
alone can execute only registered deterministic patchers.

The Fleet's autonomous lane depends on the repository-scoped App credentials.
Missing or invalid credentials fail the worker before it evaluates a merge; no
repository-token fallback silently reintroduces suppressed post-merge events.

## Sources

- [GitHub: when `GITHUB_TOKEN` triggers workflow runs](https://docs.github.com/en/actions/concepts/security/github_token#when-github_token-triggers-workflow-runs)
- [GitHub: authenticate a workflow as a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow)
- [actions/create-github-app-token: repository and permission inputs](https://github.com/actions/create-github-app-token#inputs)
