# Initial intent decisions for `infra-fleet-public`

Source: [`infra-fleet-public@65857138c50f3ab24bb8f58834c8ca3afe84a929/docs`](https://github.com/ImranAdan/infra-fleet-public/tree/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs)

Select exactly one answer for every statement. Approval confirms the `Yes`
statements; `No` statements are excluded from confirmed intent.

## 1. Purpose and scope

This is a production-like learning platform with one staging environment, not a production service. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L3-L9) · [Conflicting wording](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/README.md#L1-L4)

- [ ] Yes
- [ ] No

## 2. Monthly cost

USD 55 is the upper target for routine monthly infrastructure spend. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L3-L9)

- [ ] Yes
- [ ] No

## 3. Daily teardown

Rebuild staging on demand, destroy it after work, and use 20:00 UTC as the automatic failsafe. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/STACK-AUTOMATION.md#L21-L31) · [Conflicting schedule](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L82-L93)

- [ ] Yes
- [ ] No

## 4. Availability

Planned downtime, spot interruption, and single-node disruption are acceptable for staging. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PLATFORM-BUILD-ROADMAP.md#L9-L18)

- [ ] Yes
- [ ] No

## 5. Management boundary

Terraform manages AWS infrastructure; Flux manages Kubernetes workloads from Git; CI does not edit deployment manifests. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITOPS-SETUP.md#L8-L25)

- [ ] Yes
- [ ] No

## 6. Release safety

Canaries use 10% steps, a 50% maximum, three successful checks, success above 99%, and p99 latency below 500 ms. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PROGRESSIVE-DELIVERY.md#L92-L115)

- [ ] Yes
- [ ] No

## 7. AWS credentials

GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L1-L6)

- [ ] Yes
- [ ] No

## 8. External traffic

External application traffic must use HTTPS; HTTP is allowed only inside the cluster. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/TLS-SSL-SETUP.md#L14-L56) · [Conflicting status](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L208-L220)

- [ ] Yes
- [ ] No

## 9. Staging EKS endpoint

A public EKS API protected by AWS IAM is an accepted staging-only risk. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/EKS-ACCESS.md#L94-L116)

- [ ] Yes
- [ ] No

## 10. Destruction approval

Scheduled staging destruction does not need manual approval because the stack is ephemeral and rebuildable. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L223-L228)

- [ ] Yes
- [ ] No

## 11. Observability

Two-day Prometheus retention, a 1 GB limit, non-persistent Grafana, no Alertmanager, and port-forward-only access are acceptable for staging. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/MONITORING-SETUP.md#L68-L97)

- [ ] Yes
- [ ] No

## 12. Maintenance

Review grouped dependencies monthly, handle security updates immediately, and review the EKS version quarterly. [Evidence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md#L6-L22)

- [ ] Yes
- [ ] No
