# Initial security intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_security`
- Version: `1.6`
- Category: `security`

Source: [`infra-fleet-public@d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0`](https://github.com/ImranAdan/infra-fleet-public/tree/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0)

This catalog records security decisions only. Review changes to each proposition
as security intent; product behaviour, cost, and availability remain in their
own catalogs.

## S-001 · CI credentials

### Intent

GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.

Evidence: [OIDC design](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/GITHUB-OIDC-SETUP.md)

Caveat: the trust policy is generated from the adopter's `OWNER/REPOSITORY`,
deployment branch, and GitHub Environment inputs. Repository analysis can verify
that desired state and workflow credential method, but cannot attest which role
version is live in AWS.

### Evaluation

- Check: `github_actions_uses_oidc`

## S-002 · Workload identity

### Intent

Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.

Evidence: [application Deployment](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/deployment.yaml)

### Evaluation

- Check: `application_containers_hardened`
- Priority: `high`

## S-003 · Network ingress

### Intent

Application ingress is limited to the declared ingress, observability, Flux load
tester, and same-workload peers.

Evidence: [NetworkPolicy](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)

### Evaluation

- Check: `application_ingress_restricted`
- Priority: `high`

## S-004 · Network egress

### Intent

Permissive application egress is accepted for the current staging environment.

Evidence: [current egress policy](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)

### Evaluation

- Check: `permissive_egress_bounded`
- Priority: `medium`

## S-005 · External transport

### Intent

When an AWS staging deployment enables a public hostname, external application
traffic uses HTTPS with certificates managed by cert-manager and Let's Encrypt.

Evidence: [TLS and optional DNS](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/TLS-SSL-SETUP.md)

Caveat: the template defaults to a reserved `.invalid` hostname and port-forward
access. New public exposure remains blocked by the documented ingress-controller
migration, and repository desired state cannot prove a certificate is live.

### Evaluation

- Check: `public_ingress_https`
- Priority: `high`

## S-006 · Staging API exposure

### Intent

A publicly reachable EKS API protected by IAM is accepted for staging only.

Evidence: [staging access decision](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/EKS-ACCESS.md)

### Evaluation

- Check: `eks_public_endpoint_staging_only`
- Priority: `high`

## S-007 · IAM scope

### Intent

Service-wide IAM action wildcards such as `eks:*` are not acceptable for a
production or persistent environment.

Evidence: [current IAM disposition](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)

Caveat: the persistent policy now enumerates actions and deliberately retains
the read-only `ec2:Describe*` prefix. Several IAM write actions still use
`Resource = "*"`; that residual risk and live AWS validation are outside the
registered service-action-wildcard check.

### Evaluation

- Check: `persistent_iam_avoids_wildcards`

## S-008 · CSRF

### Intent

CSRF protection is not required for the current API-first staging application.

Evidence: [documented CSRF decision](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)

Caveat: the application is not purely API-first — when `API_KEY` is
configured, Flask session-cookie authentication protects `/ui/*` POST routes,
including endpoints that start CPU, memory, and cluster load tests. This
proposition holds only if `SameSite=Lax` is the accepted compensating
control for those routes; otherwise CSRF exposure remains.

### Evaluation

- Check: `session_cookie_csrf_compensated`
- Priority: `high`

## S-009 · Service-account tokens

### Intent

Automatic Kubernetes service-account token mounting is accepted for the current application.

Evidence: [documented token-mount decision](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)

### Evaluation

- Check: `mounted_token_unprivileged`
- Priority: `medium`

## S-010 · Security updates

### Intent

Repository owners enable dependency alerts and security-update pull requests;
routine version checks run monthly, while review and deployment remain an owned
operational decision.

Evidence: [Dependabot operating model](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/DEPENDABOT.md)

Caveat: repository-level alert and security-update settings cannot be declared
by the template, and this proposition defines no remediation SLA.

### Evaluation

- Check: `dependency_updates_configured`
- Priority: `medium`

## S-011 · Image scanning

### Intent

Trivy blocks ECR publication when an image has any fixed Critical or High vulnerability; a documented exception is required to permit one.

Evidence: [Trivy publication gate](https://github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/.github/workflows/load-harness-ci.yml)

Caveat: the workflow sets `ignore-unfixed: true`, so unfixed Critical/High
findings do not block, and the gate applies to ECR publication, not to
deployment. The proposition text above has been narrowed to match; a `Yes`
does not imply a deployment-time gate exists.

### Evaluation

- Check: `ecr_publication_scan_gated`
- Priority: `high`
