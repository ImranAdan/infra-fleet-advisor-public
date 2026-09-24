# Declaring and evaluating intent

[Documentation index](README.md)

## Write a proposition

Markdown files under `intent/` are the authoritative human interface. The
document metadata and heading names are deliberately small and strict; the
content under each `### Intent` heading is free-form Markdown and becomes the
declared proposition:

```markdown
# Platform reliability intent

- Format: `1`
- Intent ID: `platform_reliability`
- Version: `1.1`
- Category: `reliability`

## R-001 · Rollout capacity

### Intent

Owner-managed application Deployments under `k8s/applications/` retain enough
healthy capacity during rollout. Temporary capacity cost is acceptable when it
prevents user-visible interruption.

### Evaluation

- Check: `deployment_rollout_capacity`
- Priority: `high`
```

## Understand evaluation

`### Evaluation` is optional and may contain `Check`, `Priority`, or both. A
priority can therefore be recorded before evaluation support exists. Adding a
document records its propositions immediately, but its prose does not invent a
way to verify itself. Registered propositions produce exactly one of:

- `satisfied`: complete evidence supports the proposition;
- `divergent`: concrete evidence conflicts with it and produces required,
  reviewable advice; or
- `declared_unverified`: coverage or a trusted check is missing.

The maintainability intent records the Fleet's local and AWS onboarding
contract. M-001 registers a static check that can prove the common lifecycle
surface is missing or inconsistent without executing Fleet-provided code. A
structurally complete surface remains `declared_unverified` because static shell
inspection cannot prove idempotence or runtime behavior. M-002 registers a
second static check for the pinned local tool installer, checkout-owned state,
explicit Kubernetes context and printed next command. Complete controls remain
`declared_unverified` because source inspection cannot prove downloads or a
working cluster. M-003 registers `fleet_aws_onboarding`, a divergence-only check
of the AWS setup and teardown controls; see [scope and coverage](status.md).
M-004 registers `fleet_application_swappable`, a divergence-only check. It
reads the Fleet's app contracts, searches every tracked platform file for an
application name, and requires every Canary, HPA and NetworkPolicy in the
applications namespace to take its name from `${APP_NAME}`. It diverges when
the selected contract is missing, fewer than two applications ship contracts,
or the platform names or literally binds an app. It cannot prove the absence of
coupling, because a script could name an application no contract declares; an
unreadable or excluded contract leaves the result unknown unless readable
evidence already shows coupling.

The registered `deployment_rollout_capacity` check evaluates tracked `apps/v1`
Deployments sourced from `k8s/applications/` after every Fleet profile is
rendered. The collector still inventories Deployments elsewhere in the rendered
sets, but generated platform controllers do not decide this owner-managed
application proposition. For each active application Deployment the check
deterministically resolves integer or percentage rollout fenceposts against the
declared replica count. Capacity is preserved only when RollingUpdate has an
effective `maxUnavailable` of zero, a positive effective `maxSurge`, and every
application container has a readiness probe in every profile. A complete set of
conforming profile evidence can prove the proposition satisfied; an incomplete
profile or malformed, duplicate, missing, excluded, or truncated evidence leaves
it explicitly unverified.

The catalog digest is part of report provenance and material signatures. Issue
publication reloads the current catalog, requires the digest to match the merged
report, and names the source intent document and proposition in each issue.

## Unsupported intent and the work queue

Unsupported positions remain in the report's intent evaluation and collector
coverage sections. They do not create issues in either repository. Advisor
development is selected deliberately rather than generated for every unknown.
The earlier generated tickets are preserved in the
[coverage review](COVERAGE-REVIEW.md).

The work queue lives in `infra-fleet-public`. Each eligible issue comes from a
reviewed report PR and includes evidence, impact, a suggested change and the
decision-record link. Selecting issues for an agent, reviewing its proposed
fleet PRs and deciding issue closure remain maintainer actions.
