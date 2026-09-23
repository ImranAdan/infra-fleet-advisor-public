# Fleet adoption and lifecycle intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_maintainability`
- Version: `1.2`
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

- Priority: `high`
