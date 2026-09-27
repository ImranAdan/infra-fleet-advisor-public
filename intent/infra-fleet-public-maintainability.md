# Fleet adoption and lifecycle intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_maintainability`
- Version: `1.5`
- Category: `maintainability`

This document declares the fleet owner's adoption experience for the public
template. It defines the observable lifecycle contract and safety boundaries,
while leaving implementation choices to reviewed fleet changes.

## M-001 · Consistent profile lifecycle

### Intent

Every supported deployment profile exposes the same three lifecycle commands:
`./fleet setup --profile <profile>` prepares and validates the target,
`./fleet up --profile <profile>` brings the platform to a ready state, and
`./fleet down --profile <profile>` removes the resources owned by that profile.
Each phase is safe to repeat and resume after partial failure, reports its target
before mutation, and ends with either a clear success state or an actionable
failure. Successful setup and startup print the next command needed by the
adopter.

### Evaluation

- Check: `fleet_profiles_expose_lifecycle`
- Priority: `high`

## M-002 · Local first-use path

### Intent

From a clean clone on a supported workstation, an adopter can prepare the
pinned local toolchain with one `./fleet setup --profile local` command, start
the complete local platform with one `./fleet up --profile local` command, and
remove every local resource owned by that checkout with one
`./fleet down --profile local` command. The local path requires no AWS account,
HCP Terraform account, GitHub write credential, repository edit, or mutation of
the user's default Kubernetes context.

### Evaluation

- Check: `fleet_local_first_use`
- Priority: `high`

## M-003 · AWS account onboarding and teardown

### Intent

An adopter with an AWS account, an HCP Terraform organization, and a GitHub
repository supplies account-specific configuration through a non-committed
input file and existing local AWS, HCP Terraform, and GitHub CLI sessions. One
`./fleet setup --profile aws-staging` command validates the selected account,
region, organization, repository, and protected environment; configures the
required repository and HCP Terraform settings; and bootstraps the permanent
AWS foundation used for GitHub OIDC deployment. It never stores long-lived AWS
access keys in GitHub.

After setup, one `./fleet up --profile aws-staging` command deploys the reviewed
staging platform into that account through the protected GitHub environment and
short-lived AWS credentials. One `./fleet down --profile aws-staging` command
removes billable staging resources, preserves the permanent bootstrap foundation,
requires explicit confirmation of the target, and reports any resource it could
not remove. Destroying permanent bootstrap resources remains a separate,
deliberate operation.

### Evaluation

- Check: `fleet_aws_onboarding`
- Priority: `high`

## M-004 · Swappable application

### Intent

The platform runs whichever application its contract,
`k8s/fleet-app/fleet-app.yaml`, selects, and names none of its own. Routing,
progressive delivery, autoscaling, network policy, admission, the local build
and the acceptance test read the application from that contract, so replacing
the application is a contract change rather than a platform migration. At
least two applications ship contracts, so the swap stays exercised rather than
theoretical. Per-application AWS resources (its ECR repository, release
workflow and secrets) are outside this position.

### Evaluation

- Check: `fleet_application_swappable`
- Priority: `medium`

## M-005 · Autonomous merges with risk aversion

### Intent

An agent merges the pull requests it raises in this fleet and its advisor
without waiting for the owner or calling a paid model, whenever evidence alone
decides. Evidence decides when every GitHub Actions check on the exact head
commit passes, including the advisor's gate for that repository (the intent
gate for the fleet, the ratchet guard for the advisor), no review thread is
unresolved, and the pull request records its verification. The advisor is the
captain: a merge that its gate would reject never happens.

Autonomy stops where a mistake is hard to see or hard to undo. The owner still
decides changes to credentials, added or widened permissions, IAM, permanent
infrastructure, and the merge system itself. The merge system includes the
workflows, scripts and code that produce the advisor's gate checks, so no
change can approve itself by weakening its own gate.

Missing, running or failed evidence means no approval; the system never
approves by default or by timeout. Anything merged without the owner must be
reversible by reverting its merge commit, without a state, schema or data
migration.

Caveat: declaring this position grants nothing. Merges stay governed by the
merge gate's decision policy until the gate implements M-005, and that
implementation must enforce every safeguard above before any category moves
from the owner or the judge to agents. Until a check exists, the position
reports `check_not_declared` and records the owner's standing decision for
agents and reviewers.

### Evaluation

- Priority: `high`

