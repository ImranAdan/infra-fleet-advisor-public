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

A **divergence-only** check can find a conflict but never prove the position:
with complete, clean evidence it reports `declared_unverified` with reason
`collector_cannot_prove_satisfaction`. [Scope and coverage](status.md) lists
which checks are divergence-only and what each collector reads.

The catalog digest is part of report provenance and material signatures. Issue
publication reloads the current catalog, requires the digest to match the merged
report, and names the source intent document and proposition in each issue.

## Unsupported intent and the work queue

Unsupported positions remain in the report's intent evaluation and collector
coverage sections. They do not create issues in either repository. Advisor
development is selected deliberately rather than generated for every unknown
([PDR 0006](decisions/0006-report-approval-and-fleet-work.md)).

The work queue lives in `infra-fleet-public`. Each eligible issue comes from a
reviewed report PR and includes evidence, impact, a suggested change and the
decision-record link. Selecting issues for an agent, reviewing its proposed
fleet PRs and deciding issue closure remain maintainer actions.
