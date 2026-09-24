# Documentation

Start with the [project overview](../README.md) or the
[end-to-end workflow](WORKFLOW.md).

## User guides

| Guide | Purpose |
|---|---|
| [Local setup](setup.md) | Install the locked environment, run reviews and troubleshoot local inputs |
| [End-to-end workflow](WORKFLOW.md) | Run, approve, publish, select fleet work and review again |
| [Intent](intent.md) | Declare positions and understand deterministic evaluation |
| [Add a check](adding-a-check.md) | Turn one declared proposition into a bounded deterministic evaluation |
| [Reports](reports.md) | Configure report delivery, review changes and understand decline history |
| [Fleet publication](fleet-publication.md) | Configure the issues App, approve issue creation and retry safely |
| [Scope and coverage](status.md) | Understand implemented collectors, unsupported intent and limitations |

## Optional integrations

These are separate maintainer-selected paths. Fleet issue creation does not
enable them.

| Guide | Purpose |
|---|---|
| [Decision feedback](feedback.md) | Turn labelled fleet decisions into reviewed policy proposals |
| [Mechanical remediation](remediation.md) | Preview or propose the narrowly supported mechanical patch |

## Contribution and security

- [Contributing](../CONTRIBUTING.md): development setup, checks and PR expectations.
- [Security](../SECURITY.md): access boundaries, untrusted inputs and disclosure.
- [Repository guidance](../AGENTS.md): instructions for agents working here.

## Specifications

These describe the product and implementation in more detail than the guides.

- [Product requirements](product-requirements.md)
- [Architecture](architecture.md)
- [Product research](product-research.md)
- [Coverage review](COVERAGE-REVIEW.md): history of the retired generated backlog.

## Product decision records

| Record | Decision |
|---|---|
| [0001](decisions/0001-advisory-delivery-and-feedback-loop.md) | Advisory delivery and policy feedback |
| [0002](decisions/0002-mechanical-remediation-of-the-fleet.md) | Optional mechanical remediation |
| [0003](decisions/0003-intent-compilation-and-divergence-delivery.md) | Intent compilation and guaranteed divergence delivery |
| [0004](decisions/0004-intent-driven-capability-evolution.md) | Superseded capability-ticket approach; retained as history |
| [0005](decisions/0005-public-project-language.md) | Public project language |
| [0006](decisions/0006-report-approval-and-fleet-work.md) | Approved report PRs as the fleet issue-creation decision record |
| [0007](decisions/0007-pre-merge-intent-gate.md) | Read-only intent gate on fleet pull requests |
