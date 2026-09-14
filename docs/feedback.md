# Recording fleet decisions in policy

[Documentation index](README.md)

This optional integration is disabled unless `FLEET_FEEDBACK_ENABLED=true`.
It uses the issues-App credentials described in the
[publication guide](fleet-publication.md), with the token restricted to
`issues: read`. Enabling issue publication alone does not enable feedback.

## Record an accepted trade-off

To decline an advisor issue as an accepted trade-off, a maintainer closes the
issue and applies `advisor:wontfix` plus exactly one reason label:

- `advisor:tradeoff:availability`
- `advisor:tradeoff:compatibility`
- `advisor:tradeoff:complexity`
- `advisor:tradeoff:cost`
- `advisor:tradeoff:risk-accepted`

## Review the policy proposal

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

## Changed decisions and retries

If the issue is reopened or either decision label is removed before merge, the
workflow withdraws its own stale policy pull request. That automated closure is
marked as a cancellation and does not count as a maintainer declining the plan.
If a push succeeds but pull-request creation fails, the next run can reclaim the
reserved `advisor/feedback-wontfix` branch only after proving it is a
single-parent commit from merged history that changes only `policy.yaml`.

After a feedback policy or intent catalog change, this job waits for an advisory
report made under the current versions. A feedback-policy report keeps the
finding visible with the accepted rationale while making it ineligible for issue
publication and mechanical remediation.

Feedback policy proposals still use `GITHUB_TOKEN`; see the
[report guide](reports.md) for the limitation on automatically triggering
ordinary PR checks. This path proposes policy only and never merges it.
