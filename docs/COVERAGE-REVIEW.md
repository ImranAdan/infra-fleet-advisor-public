# Coverage review

This snapshot consolidates the sixteen advisor capability tickets generated
from [report PR #27](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/27)
on 14 September 2026. They describe evaluation limits, not sixteen verified
fleet defects. [PDR 0006](decisions/0006-report-approval-and-fleet-work.md)
supersedes their automatic publication. Closing the tickets does not mean the
checks are implemented; current coverage remains in every report.

| Intent | Evaluation limit or subject | Historical ticket |
|---|---|---|
| Security S-007 | Registered persistent-stack IAM check; bounded dynamic syntax is supported while referenced policies remain unverified in scope | [#30](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/30) |
| Security S-006 | No check for the staging EKS API access decision | [#31](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/31) |
| Cost C-003 | No log-retention check | [#32](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/32) |
| Cost C-001 | No scheduled worker-capacity check | [#33](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/33) |
| Cost C-005 | No resource-tagging check | [#34](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/34) |
| Security S-004 | No check for the accepted staging egress policy | [#35](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/35) |
| Cost C-004 | No ECR lifecycle-policy check | [#36](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/36) |
| Security S-008 | No check for the CSRF decision | [#37](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/37) |
| Security S-003 | No application ingress NetworkPolicy check | [#38](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/38) |
| Security S-010 | No check for dependency remediation timing | [#39](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/39) |
| Security S-005 | No TLS desired-state check | [#40](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/40) |
| Security S-002 | No container security-context check | [#41](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/41) |
| Cost C-002 | No bounded demand-driven worker-scaling check | [#42](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/42) |
| Security S-001 | Existing OIDC check cannot prove the complete proposition satisfied | [#43](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/43) |
| Security S-011 | No check bound to the declared fixed-vulnerability publication gate | [#44](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/44) |
| Security S-009 | No service-account token-mount decision check | [#45](https://github.com/ImranAdan/infra-fleet-advisor-public/issues/45) |

Advisor development is chosen deliberately from observed value. Completing a
collector or check does not itself create fleet work. A subsequent report must
capture conflicting evidence, a reviewer must merge that report PR, and the
separate publisher must validate the applicable finding.

The rollout position R-001 is scoped to owner-managed Deployments under
`k8s/applications/`; Flux's generated controllers remain collected inventory but
do not create application rollout work. S-007 collection is scoped to the
persistent Terraform stack, matching its trusted rule. A staging-only external
policy therefore cannot block lifecycle resolution of historical persistent IAM
recommendations.
