# Initial security intent for `infra-fleet-public`

Source: [`infra-fleet-public@65857138c50f3ab24bb8f58834c8ca3afe84a929/docs`](https://github.com/ImranAdan/infra-fleet-public/tree/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs)

This PR contains security decisions only. Review each proposition with an
inline `Yes` or `No` comment. Product behaviour, cost, and availability are out
of scope.

## S-001 · CI credentials

GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.

Evidence: [OIDC design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L1-L6)

## S-002 · Workload identity

Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.

Evidence: [pod security context](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L20-L46)

## S-003 · Network ingress

Application ingress is limited to the NGINX ingress and Prometheus namespaces.

Evidence: [NetworkPolicy](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L50-L87)

## S-004 · Network egress

Permissive application egress is accepted for the current staging environment.

Evidence: [current egress policy](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L78-L87)

## S-005 · External transport

External application traffic uses HTTPS with certificates managed by cert-manager and Let’s Encrypt.

Evidence: [TLS design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/TLS-SSL-SETUP.md#L5-L13) · [conflicting deferred entry](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L208-L220)

## S-006 · Staging API exposure

A publicly reachable EKS API protected by IAM is accepted for staging only.

Evidence: [staging access decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/EKS-ACCESS.md#L94-L116)

## S-007 · IAM scope

Wildcard IAM permissions are not acceptable for a production or persistent environment.

Evidence: [deferred least-privilege concern](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L247-L252)

## S-008 · Destructive workflows

Scheduled staging destruction may run without manual approval because the stack is ephemeral and rebuildable.

Evidence: [accepted workflow risk](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L223-L228)

## S-009 · CSRF

CSRF protection is not required for the current API-first staging application.

Evidence: [documented CSRF decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L231-L235)

## S-010 · Service-account tokens

Automatic Kubernetes service-account token mounting is accepted for the current application.

Evidence: [documented token-mount decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L239-L243)

## S-011 · Security updates

Security dependency updates are handled immediately rather than waiting for the routine monthly update cycle.

Evidence: [Dependabot security alerts](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md#L54-L60)

## S-012 · Image scanning

Container vulnerability scans block images with unacceptable findings before deployment.

Evidence: [Trivy security control](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L277-L283)
