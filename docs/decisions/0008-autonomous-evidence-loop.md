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
the marker holds a PR.

Changed report PRs opt in automatically. Their merge remains the immutable
decision record for Fleet issue publication, but the decision is now made by
declared intent plus deterministic exact-head evidence. Closing a report PR
still records a decline of that material signature.

Both generated PR paths use `GITHUB_TOKEN`. Because GitHub suppresses ordinary
pull-request workflow events created by that token, trusted default-branch code
explicitly dispatches a read-only validation workflow on the generated branch.
No App credential or personal token is needed. The dispatch resolves and checks
the PR's exact base and head before producing evidence.

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
