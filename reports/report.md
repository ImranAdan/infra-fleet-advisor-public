# Infra Fleet Advisor report

- Source: `infra-fleet-public` @ `65857138c50f3ab24bb8f58834c8ca3afe84a929`
- Advisor version: `0.1.0` · Policy version: `1.0`
- Model: `stub-synthesizer-v1` · Run started: `2026-09-10T19:27:01.332000+00:00`
- Intent catalog: `intent-md-v1:5f008a8b1cfb9677c8dccf0240293c04dd351869ff55bbdb12430a750e2386c5`
- Lifecycle: 1 new, 1 unchanged, 1 resolved, 0 suppressed (2 rejected)

## Collector coverage

- `github_actions_workflow_collector`: ok (13 evidence)
- `terraform_iam_collector`: ok (1 evidence)
- `kubernetes_deployment_collector`: ok (7 evidence)

## Intent evaluation

- `divergent` `infra_fleet_public_reliability/R-001` — Deployments retain enough healthy capacity during rollout. Temporary capacity
  cost is acceptable when it prevents user-visible interruption.
  - Category: `reliability` · Priority: `high` · Check: `deployment_rollout_capacity` · Reason: `evidence_conflicts_with_intent`
  - Evidence: `kubernetes_deployment_collector:21df164d364775d0`, `kubernetes_deployment_collector:3fb87f240e478035`
- `declared_unverified` `infra_fleet_public_security/S-001` — GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.
  
  Evidence: \[OIDC design\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md\#L1-L6)
  
  Caveat: \`infrastructure/permanent/github-oidc.tf\` at the cited commit binds the
  trust policy subject to the placeholder \`repo:your-org/infra-fleet:\*\`, which
  does not match \`ImranAdan/infra-fleet-public\`. As deployed, AWS STS would deny
  this role to GitHub Actions; verify the actual deployed subject before relying
  on this control.
  - Category: `security` · Priority: `high` · Check: `github_actions_uses_oidc` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_security/S-002` — Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.
  
  Evidence: \[pod security context\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L20-L46)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-003` — Application ingress is limited to the NGINX ingress and Prometheus namespaces.
  
  Evidence: \[NetworkPolicy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L50-L87)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-004` — Permissive application egress is accepted for the current staging environment.
  
  Evidence: \[current egress policy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L78-L87)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-005` — External application traffic uses HTTPS with certificates managed by cert-manager and Let’s Encrypt.
  
  Evidence: \[TLS design\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/TLS-SSL-SETUP.md\#L5-L13) · \[conflicting deferred entry\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L208-L220)
  
  Caveat: the two evidence sources conflict — \`SECURITY-CONCERNS.md\`'s C3 entry
  still documents TLS as deferred/unencrypted. Verify the deployed endpoint and
  certificate configuration before treating this proposition as resolved.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-006` — A publicly reachable EKS API protected by IAM is accepted for staging only.
  
  Evidence: \[staging access decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/EKS-ACCESS.md\#L94-L116)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `divergent` `infra_fleet_public_security/S-007` — Wildcard IAM permissions are not acceptable for a production or persistent environment.
  
  Evidence: \[deferred least-privilege concern\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L247-L252)
  
  Caveat: \`infrastructure/permanent/github-oidc.tf\` — the current persistent
  stack — grants \`eks:\*\`, \`ec2:\*\`, \`autoscaling:\*\`, \`ssm:\*\`, and \`ecr:\*\` on \`\*\`
  today. A \`Yes\` on this proposition is a gate to remediate that role, not a
  statement that the persistent stack already complies.
  - Category: `security` · Priority: `critical` · Check: `persistent_iam_avoids_wildcards` · Reason: `evidence_conflicts_with_intent`
  - Evidence: `terraform_iam_collector:00dfe82f2366c9e7`
- `declared_unverified` `infra_fleet_public_security/S-008` — CSRF protection is not required for the current API-first staging application.
  
  Evidence: \[documented CSRF decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L231-L235)
  
  Caveat: the application is not purely API-first — when \`API\_KEY\` is
  configured, Flask session-cookie authentication protects \`/ui/\*\` POST routes,
  including endpoints that start CPU, memory, and cluster load tests. This
  proposition holds only if \`SameSite=Lax\` is the accepted compensating
  control for those routes; otherwise CSRF exposure remains.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-009` — Automatic Kubernetes service-account token mounting is accepted for the current application.
  
  Evidence: \[documented token-mount decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L239-L243)
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-010` — Security dependency updates are handled immediately rather than waiting for the routine monthly update cycle.
  
  Evidence: \[Dependabot security alerts\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md\#L54-L60)
  
  Caveat: the cited evidence covers immediate alerting and priority PR
  creation only; review, merge, and deployment remain manual with no stated
  owner or remediation deadline. Treat "handled immediately" as scoped to
  alerting and PR creation, not an end-to-end SLA.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`
- `declared_unverified` `infra_fleet_public_security/S-011` — Trivy blocks ECR publication when an image has any fixed Critical or High vulnerability; a documented exception is required to permit one.
  
  Evidence: \[Trivy security control\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md\#L277-L283)
  
  Caveat: the workflow sets \`ignore-unfixed: true\`, so unfixed Critical/High
  findings do not block, and the gate applies to ECR publication, not to
  deployment. The proposition text above has been narrowed to match; a \`Yes\`
  does not imply a deployment-time gate exists.
  - Category: `security` · Priority: `not_declared` · Check: `not_declared` · Reason: `check_not_declared`

## Recommendations

### #1 [unchanged] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_6a206c70c062521f8d4d2145`
- Evidence: `terraform_iam_collector:00dfe82f2366c9e7`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.

### #2 [new] Deployment rollout can reduce healthy capacity

- Category: `reliability` · Priority: `high` · Confidence: 0.95
- Fingerprint: `fp_aaa9b490f08e5576be4b13a8`
- Evidence: `kubernetes_deployment_collector:21df164d364775d0`, `kubernetes_deployment_collector:3fb87f240e478035`

A declared Kubernetes Deployment can make existing healthy capacity unavailable before replacement capacity is ready.

**Impact:** A routine rollout can interrupt service or reduce the workload below its declared replica capacity.

**Suggested change:** Use RollingUpdate with an effective maxUnavailable of 0 and a positive maxSurge, and define a readiness probe for every application container.

**Trade-offs:** Zero-unavailable rollouts temporarily consume surge capacity and may require extra cluster headroom.

### [resolved] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_b3cb0f1396ed1d3f4d4518b4`
- Evidence: `terraform_iam_collector:f9516f33c203f5c8`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.


## Rejected candidates

- `deployment_rollout_capacity_loss` (`reliability`) — not_a_compiled_intent_divergence
- `deployment_rollout_capacity_loss` (`reliability`) — not_a_compiled_intent_divergence
