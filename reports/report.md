# Infra Fleet Advisor report

- Source: `infra-fleet-public` @ `f3c42956a63066568e7d7133f41b053cd58293ac`
- Advisor version: `0.1.0` · Policy version: `1.1`
- Model: `stub-synthesizer-v1` · Run started: `2026-09-23T23:26:58.767965+00:00`
- Intent catalog: `intent-md-v1:e9386fb7406828b843cb906fd839177e90e13867a69dd2fbda512028fa48549f`
- Lifecycle: 1 new, 1 unchanged, 2 resolved, 0 suppressed (0 rejected)

## Collector coverage

- `github_actions_workflow_collector`: ok (13 evidence)
- `terraform_iam_collector`: ok (0 evidence)
- `terraform_cost_collector`: ok (2 evidence)
- `kubernetes_deployment_collector`: ok (14 evidence)
- `fleet_lifecycle_collector`: ok (3 evidence)

## Intent evaluation

**Coverage:** 9 of 20 positions have a check — 3 satisfied, 2 divergent, 4 checked but unproven; 11 declared without a check.

- `declared_unverified` `infra_fleet_public_cost/C-001` — Staging application worker capacity scales to zero outside an owner-defined
  usage window. A delayed startup of up to 30 minutes is acceptable when it avoids
  paying for otherwise idle compute.
  - Category: `cost` · Priority: `high` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_cost/C-002` — Every non-production EKS worker group declares demand-driven scaling with a zero
  minimum where its workloads permit it and an explicit bounded maximum. Any
  always-on baseline must name the workload that requires it.
  - Category: `cost` · Priority: `high` · Check: `not_declared` · Reason: `check_not_declared`
- `divergent` `infra_fleet_public_cost/C-003` — Every staging CloudWatch log group managed by the fleet has an explicit
  retention period of no more than 30 days. Longer retention requires a documented
  operational or compliance reason.
  - Category: `cost` · Priority: `medium` · Check: `staging_log_retention_bounded` · Reason: `evidence_conflicts_with_intent`
  - Evidence: `terraform_cost_collector:d2d6fa1dfde83257`
- `satisfied` `infra_fleet_public_cost/C-004` — Every ECR repository managed by the fleet has a lifecycle policy that removes
  untagged images and bounds the number or age of retained images. Images retained
  for rollback or audit have an explicit exception.
  - Category: `cost` · Priority: `medium` · Check: `ecr_lifecycle_bounded` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_cost/C-005` — Terraform-managed AWS resources that support tagging declare consistent
  environment, service, and owner tags so billed usage can be attributed. Any
  resource that cannot carry these tags is reported as an explicit coverage gap.
  - Category: `cost` · Priority: `medium` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_maintainability/M-001` — Every supported deployment profile exposes the same three lifecycle commands:
  \`./fleet setup --profile \<profile\>\` prepares and validates the target,
  \`./fleet up --profile \<profile\>\` brings the platform to a ready state, and
  \`./fleet down --profile \<profile\>\` removes the resources owned by that profile.
  Each phase is safe to repeat and resume after partial failure, reports its target
  before mutation, and ends with either a clear success state or an actionable
  failure. Successful setup and startup print the next command needed by the
  adopter.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_profiles_expose_lifecycle` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_maintainability/M-002` — From a clean clone on a supported workstation, an adopter can prepare the
  pinned local toolchain with one \`./fleet setup --profile local\` command, start
  the complete local platform with one \`./fleet up --profile local\` command, and
  remove every local resource owned by that checkout with one
  \`./fleet down --profile local\` command. The local path requires no AWS account,
  HCP Terraform account, GitHub write credential, repository edit, or mutation of
  the user's default Kubernetes context.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_local_first_use` · Reason: `collector_cannot_prove_satisfaction`
- `divergent` `infra_fleet_public_maintainability/M-003` — An adopter with an AWS account, an HCP Terraform organization, and a GitHub
  repository supplies account-specific configuration through a non-committed
  input file and existing local AWS, HCP Terraform, and GitHub CLI sessions. One
  \`./fleet setup --profile aws-staging\` command validates the selected account,
  region, organization, repository, and protected environment; configures the
  required repository and HCP Terraform settings; and bootstraps the permanent
  AWS foundation used for GitHub OIDC deployment. It never stores long-lived AWS
  access keys in GitHub.
  
  After setup, one \`./fleet up --profile aws-staging\` command deploys the reviewed
  staging platform into that account through the protected GitHub environment and
  short-lived AWS credentials. One \`./fleet down --profile aws-staging\` command
  removes billable staging resources, preserves the permanent bootstrap foundation,
  requires explicit confirmation of the target, and reports any resource it could
  not remove. Destroying permanent bootstrap resources remains a separate,
  deliberate operation.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_aws_onboarding` · Reason: `evidence_conflicts_with_intent`
  - Evidence: `fleet_lifecycle_collector:9fe9dbe2d300812e`
- `satisfied` `infra_fleet_public_reliability/R-001` — Owner-managed application Deployments under \`k8s/applications/\` retain enough
  healthy capacity during rollout. Temporary capacity cost is acceptable when it
  prevents user-visible interruption.
  - Category: `reliability` · Priority: `high` · Check: `deployment_rollout_capacity` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-001` — GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.
  
  Evidence: \[OIDC design\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/GITHUB-OIDC-SETUP.md)
  
  Caveat: the trust policy is generated from the adopter's \`OWNER/REPOSITORY\`,
  deployment branch, and GitHub Environment inputs. Repository analysis can verify
  that desired state and workflow credential method, but cannot attest which role
  version is live in AWS.
  - Category: `security` · Priority: `high` · Check: `github_actions_uses_oidc` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_security/S-002` — Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.
  
  Evidence: \[application Deployment\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/deployment.yaml)
  - Category: `security` · Priority: `high` · Check: `application_containers_hardened` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-003` — Application ingress is limited to the declared ingress, observability, Flux load
  tester, and same-workload peers.
  
  Evidence: \[NetworkPolicy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-004` — Permissive application egress is accepted for the current staging environment.
  
  Evidence: \[current egress policy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-005` — When an AWS staging deployment enables a public hostname, external application
  traffic uses HTTPS with certificates managed by cert-manager and Let's Encrypt.
  
  Evidence: \[TLS and optional DNS\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/TLS-SSL-SETUP.md)
  
  Caveat: the template defaults to a reserved \`.invalid\` hostname and port-forward
  access. New public exposure remains blocked by the documented ingress-controller
  migration, and repository desired state cannot prove a certificate is live.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-006` — A publicly reachable EKS API protected by IAM is accepted for staging only.
  
  Evidence: \[staging access decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/EKS-ACCESS.md)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-007` — Service-wide IAM action wildcards such as \`eks:\*\` are not acceptable for a
  production or persistent environment.
  
  Evidence: \[current IAM disposition\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  
  Caveat: the persistent policy now enumerates actions and deliberately retains
  the read-only \`ec2:Describe\*\` prefix. Several IAM write actions still use
  \`Resource = "\*"\`; that residual risk and live AWS validation are outside the
  registered service-action-wildcard check.
  - Category: `security` · Priority: `critical` · Check: `persistent_iam_avoids_wildcards` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_security/S-008` — CSRF protection is not required for the current API-first staging application.
  
  Evidence: \[documented CSRF decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  
  Caveat: the application is not purely API-first — when \`API\_KEY\` is
  configured, Flask session-cookie authentication protects \`/ui/\*\` POST routes,
  including endpoints that start CPU, memory, and cluster load tests. This
  proposition holds only if \`SameSite=Lax\` is the accepted compensating
  control for those routes; otherwise CSRF exposure remains.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-009` — Automatic Kubernetes service-account token mounting is accepted for the current application.
  
  Evidence: \[documented token-mount decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-010` — Repository owners enable dependency alerts and security-update pull requests;
  routine version checks run monthly, while review and deployment remain an owned
  operational decision.
  
  Evidence: \[Dependabot operating model\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/DEPENDABOT.md)
  
  Caveat: repository-level alert and security-update settings cannot be declared
  by the template, and this proposition defines no remediation SLA.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-011` — Trivy blocks ECR publication when an image has any fixed Critical or High vulnerability; a documented exception is required to permit one.
  
  Evidence: \[Trivy publication gate\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/.github/workflows/load-harness-ci.yml)
  
  Caveat: the workflow sets \`ignore-unfixed: true\`, so unfixed Critical/High
  findings do not block, and the gate applies to ECR publication, not to
  deployment. The proposition text above has been narrowed to match; a \`Yes\`
  does not imply a deployment-time gate exists.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`

## Recommendations

### #1 [new] AWS staging lifecycle lacks a declared onboarding or teardown control

- Category: `maintainability` · Priority: `high` · Confidence: 0.90
- Fingerprint: `fp_1b74b45b8223503fca7d7a49`
- Evidence: `fleet_lifecycle_collector:9fe9dbe2d300812e`

The aws-staging strategy or its onboarding coordinator does not show every static control: plan-by-default setup, reported targets, stdin-only secrets, a next command, and a teardown confirmation typed by the operator.

**Impact:** An adopter can mutate or destroy a billable AWS target without first seeing and confirming it, or leak a credential through process arguments.

**Suggested change:** Keep setup in plan mode unless --apply is given, print the AWS and GitHub targets before mutation, pipe secrets to gh secret set, print the next lifecycle command, and have down show its target and pass the operator's typed confirmation to the teardown workflow instead of a hard-coded one.

**Trade-offs:** Interactive confirmation makes unattended teardown require an explicit, separately supplied confirmation value.

### #2 [unchanged] Staging CloudWatch log group keeps logs longer than 30 days

- Category: `cost` · Priority: `medium` · Confidence: 0.90
- Fingerprint: `fp_71b389eab950ffc8b4efa99c`
- Evidence: `terraform_cost_collector:d2d6fa1dfde83257`

A staging log group declared directly or created by a pinned module retains events for more than 30 days or never expires them.

**Impact:** Log storage grows with every rebuild cycle and is billed after the staging environment's usefulness for debugging has passed.

**Suggested change:** Declare an explicit retention of at most 30 days, for the EKS module via cloudwatch_log_group_retention_in_days, or document why longer retention is needed.

**Trade-offs:** Shorter retention removes older control-plane audit trails that could help a late incident investigation.

### [resolved] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_6a206c70c062521f8d4d2145`
- Evidence: `terraform_iam_collector:00dfe82f2366c9e7`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.

### [resolved] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_b3cb0f1396ed1d3f4d4518b4`
- Evidence: `terraform_iam_collector:f9516f33c203f5c8`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.
