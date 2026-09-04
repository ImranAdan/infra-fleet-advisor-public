# Initial security intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_security`
- Version: `1.0`
- Category: `security`

Source: [`infra-fleet-public@65857138c50f3ab24bb8f58834c8ca3afe84a929/docs`](https://github.com/ImranAdan/infra-fleet-public/tree/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs)

This PR contains security decisions only. Review each proposition with an
inline `Yes` or `No` comment. Product behaviour, cost, and availability are out
of scope.

## S-001 · CI credentials

### Intent

GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.

Evidence: [OIDC design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L1-L6)

Caveat: `infrastructure/permanent/github-oidc.tf` at the cited commit binds the
trust policy subject to the placeholder `repo:your-org/infra-fleet:*`, which
does not match `ImranAdan/infra-fleet-public`. As deployed, AWS STS would deny
this role to GitHub Actions; verify the actual deployed subject before relying
on this control.

### Evaluation

- Check: `github_actions_uses_oidc`

## S-002 · Workload identity

### Intent

Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.

Evidence: [pod security context](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L20-L46)

## S-003 · Network ingress

### Intent

Application ingress is limited to the NGINX ingress and Prometheus namespaces.

Evidence: [NetworkPolicy](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L50-L87)

## S-004 · Network egress

### Intent

Permissive application egress is accepted for the current staging environment.

Evidence: [current egress policy](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L78-L87)

## S-005 · External transport

### Intent

External application traffic uses HTTPS with certificates managed by cert-manager and Let’s Encrypt.

Evidence: [TLS design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/TLS-SSL-SETUP.md#L5-L13) · [conflicting deferred entry](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L208-L220)

Caveat: the two evidence sources conflict — `SECURITY-CONCERNS.md`'s C3 entry
still documents TLS as deferred/unencrypted. Verify the deployed endpoint and
certificate configuration before treating this proposition as resolved.

## S-006 · Staging API exposure

### Intent

A publicly reachable EKS API protected by IAM is accepted for staging only.

Evidence: [staging access decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/EKS-ACCESS.md#L94-L116)

## S-007 · IAM scope

### Intent

Wildcard IAM permissions are not acceptable for a production or persistent environment.

Evidence: [deferred least-privilege concern](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L247-L252)

Caveat: `infrastructure/permanent/github-oidc.tf` — the current persistent
stack — grants `eks:*`, `ec2:*`, `autoscaling:*`, `ssm:*`, and `ecr:*` on `*`
today. A `Yes` on this proposition is a gate to remediate that role, not a
statement that the persistent stack already complies.

### Evaluation

- Check: `persistent_iam_avoids_wildcards`

## S-008 · CSRF

### Intent

CSRF protection is not required for the current API-first staging application.

Evidence: [documented CSRF decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L231-L235)

Caveat: the application is not purely API-first — when `API_KEY` is
configured, Flask session-cookie authentication protects `/ui/*` POST routes,
including endpoints that start CPU, memory, and cluster load tests. This
proposition holds only if `SameSite=Lax` is the accepted compensating
control for those routes; otherwise CSRF exposure remains.

## S-009 · Service-account tokens

### Intent

Automatic Kubernetes service-account token mounting is accepted for the current application.

Evidence: [documented token-mount decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L239-L243)

## S-010 · Security updates

### Intent

Security dependency updates are handled immediately rather than waiting for the routine monthly update cycle.

Evidence: [Dependabot security alerts](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md#L54-L60)

Caveat: the cited evidence covers immediate alerting and priority PR
creation only; review, merge, and deployment remain manual with no stated
owner or remediation deadline. Treat "handled immediately" as scoped to
alerting and PR creation, not an end-to-end SLA.

## S-011 · Image scanning

### Intent

Trivy blocks ECR publication when an image has any fixed Critical or High vulnerability; a documented exception is required to permit one.

Evidence: [Trivy security control](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L277-L283)

Caveat: the workflow sets `ignore-unfixed: true`, so unfixed Critical/High
findings do not block, and the gate applies to ECR publication, not to
deployment. The proposition text above has been narrowed to match; a `Yes`
does not imply a deployment-time gate exists.
