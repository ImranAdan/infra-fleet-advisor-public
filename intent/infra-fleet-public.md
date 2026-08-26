# Initial intent decisions for `infra-fleet-public`

Source: [`infra-fleet-public@65857138c50f3ab24bb8f58834c8ca3afe84a929/docs`](https://github.com/ImranAdan/infra-fleet-public/tree/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs)

These are independent propositions, not confirmed intent yet. Review each
section in this pull request with an inline `Yes` or `No` comment. A `No`
decision excludes that proposition; a requested replacement should be added as
a follow-up change. Approval confirms the propositions marked `Yes` after the
review is complete.

## I-001 · Purpose

The fleet is a production-like learning and demonstration platform, not a production service.

Evidence: [cost guide](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L3-L9) · [conflicting production wording](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/README.md#L1-L4)

## I-002 · Current environment

The current supported environment is `staging`.

Evidence: [single staging environment](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-ENVIRONMENTS.md#L76-L89)

## I-003 · Production scope

Production and multi-environment operation require a separate approved intent.

Evidence: [production design deferred for cost](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/MULTI-ENVIRONMENT-DESIGN.md#L1-L16)

## I-004 · Routine cost target

USD 55 is the upper target for routine monthly infrastructure spend.

Evidence: [current USD 45–55 target](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L3-L9)

## I-005 · Rebuild operation

Staging is rebuilt on demand rather than kept continuously available.

Evidence: [manual rebuild pattern](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L17-L22)

## I-006 · Destroy operation

Staging is destroyed after the work session ends.

Evidence: [manual destroy guidance](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/COST-OPTIMIZATION-GUIDE.md#L17-L22)

## I-007 · Destroy failsafe

The automatic staging-destruction failsafe runs at 20:00 UTC.

Evidence: [20:00 UTC hard stop](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/STACK-AUTOMATION.md#L21-L31) · [older conflicting schedule](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L82-L93)

## I-008 · Planned downtime

Planned downtime is acceptable for staging.

Evidence: [accepted single-node downtime](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PLATFORM-BUILD-ROADMAP.md#L9-L18)

## I-009 · Spot interruption

Spot-instance interruption risk is acceptable for staging.

Evidence: [spot instances and cost trade-off](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PLATFORM-BUILD-ROADMAP.md#L9-L18)

## I-010 · Single-node operation

A single worker node is acceptable for staging.

Evidence: [single worker node](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PLATFORM-BUILD-ROADMAP.md#L9-L18)

## I-011 · AWS ownership

Terraform is the owner of AWS infrastructure resources.

Evidence: [Terraform responsibility](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITOPS-SETUP.md#L8-L25)

## I-012 · Kubernetes ownership

Flux is the owner of Kubernetes workload state from Git.

Evidence: [Flux responsibility](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITOPS-SETUP.md#L8-L25)

## I-013 · CI manifest boundary

CI does not directly edit Kubernetes deployment manifests.

Evidence: [Flux image update flow](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITOPS-SETUP.md#L305-L318)

## I-014 · Application versioning

The application uses SemVer and release-please.

Evidence: [application versioning](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/VERSIONING-STRATEGY.md#L1-L17)

## I-015 · Canary progression

Application releases use canary traffic progression in 10 percent steps up to 50 percent.

Evidence: [canary settings](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PROGRESSIVE-DELIVERY.md#L92-L101)

## I-016 · Success-rate gate

Canary promotion requires request success above 99 percent.

Evidence: [success-rate threshold](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PROGRESSIVE-DELIVERY.md#L103-L115)

## I-017 · Latency gate

Canary promotion requires p99 latency below 500 milliseconds.

Evidence: [latency threshold](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PROGRESSIVE-DELIVERY.md#L103-L115)

## I-018 · AWS credentials

GitHub Actions uses short-lived OIDC credentials and no long-lived AWS access keys.

Evidence: [OIDC design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/GITHUB-OIDC-SETUP.md#L1-L6)

## I-019 · External transport

External application traffic uses HTTPS.

Evidence: [external HTTPS design](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/TLS-SSL-SETUP.md#L14-L56) · [conflicting deferred entry](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L208-L220)

## I-020 · Public staging endpoint

A publicly reachable EKS API protected by IAM is acceptable for staging.

Evidence: [staging endpoint decision](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/EKS-ACCESS.md#L94-L116)

## I-021 · Destruction approval

Scheduled staging destruction does not require manual approval.

Evidence: [accepted workflow risk](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/SECURITY-CONCERNS.md#L223-L228)

## I-022 · Monitoring access

Staging monitoring is accessed through local port forwarding.

Evidence: [port-forward access](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/MONITORING-SETUP.md#L41-L57)

## I-023 · Monitoring retention

Two-day Prometheus retention and a 1 GB storage limit are acceptable for staging.

Evidence: [Prometheus limits](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/MONITORING-SETUP.md#L68-L80)

## I-024 · Dashboard persistence

Non-persistent Grafana and no Alertmanager are acceptable for staging.

Evidence: [disabled persistence and components](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/MONITORING-SETUP.md#L82-L97)

## I-025 · Dependency cadence

Routine dependency updates are reviewed monthly in grouped pull requests.

Evidence: [Dependabot cadence](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md#L6-L22)

## I-026 · Security update priority

Security dependency updates are handled outside the routine monthly cadence.

Evidence: [security update priority](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/DEPENDABOT.md#L54-L60)

## I-027 · EKS version cadence

The EKS version is reviewed at least quarterly, before extended support begins.

Evidence: [EKS lifecycle guidance](https://github.com/ImranAdan/infra-fleet-public/blob/65857138c50f3ab24bb8f58834c8ca3afe84a929/docs/PLATFORM-BUILD-ROADMAP.md#L418-L425)
