# Product requirements

## Product definition

Infra Fleet Advisor is a scheduled, read-only repository advisor that converts
the desired state and validation signals in `infra-fleet-public` into a
prioritized improvement backlog.

It helps the repository owner answer:

> Given the fleet's current intent and accepted constraints, what are the most
> valuable improvements to consider next, and what evidence supports them?

## Primary user

The MVP serves the owner and maintainer of `infra-fleet-public`. It assumes the
user understands GitOps and can decide whether a recommendation should become
work. Broader multi-team or multi-repository use is outside the MVP.

## Desired outcome

Reduce the effort required to inspect the fleet, reconcile scattered signals,
and maintain a credible improvement backlog without granting an AI system
permission to change infrastructure.

## Product principles

- **Evidence before advice:** every recommendation cites captured repository
  evidence.
- **Intent before convention:** configured goals and accepted trade-offs take
  precedence over generic best practices.
- **Deterministic boundaries:** code owns source verification, schema
  validation, limits, lifecycle state, and publication eligibility.
- **AI as an untrusted analyst:** a model may synthesize evidence but cannot
  expand its permissions or publish unsupported claims.
- **Small, useful output:** prioritization is more valuable than exhaustive
  commentary.
- **Read-only by default:** repository and infrastructure mutation require a
  future, explicitly approved product phase.

## MVP inputs

1. A clean, complete checkout of `infra-fleet-public`.
2. The full Git commit SHA expected for that checkout.
3. A versioned advisor policy defining priorities, accepted trade-offs,
   exclusions, and recommendation limits.
4. Deterministic collector results produced during the run.
5. An optional prior recommendation report for lifecycle comparison.

The MVP must not require AWS credentials, Kubernetes credentials, Terraform
state access, or secrets from the target fleet.

## Advisory categories

The initial taxonomy is:

- `security`
- `reliability`
- `cost`
- `lifecycle`
- `maintainability`
- `gitops_correctness`

Categories organize recommendations; they do not create separate autonomous
agents.

## Recommendation contract

Each recommendation must contain:

| Field | Meaning |
| --- | --- |
| `fingerprint` | Stable identifier derived from category, concern, and stable evidence identity. |
| `category` | One value from the configured taxonomy. |
| `priority` | Bounded rank such as critical, high, medium, or low. |
| `title` | Concise actionable summary. |
| `summary` | What should be considered and why. |
| `evidence` | One or more validated evidence IDs resolving to repository-relative facts. |
| `impact` | Expected benefit or avoided risk. |
| `suggested_change` | A bounded proposal, not an automatically executed action. |
| `trade_offs` | Cost, complexity, availability, or maintenance consequences. |
| `confidence` | Bounded score with an explanation of uncertainty. |
| `status` | New, unchanged, resolved, or suppressed. |

Evidence records are created by deterministic collectors and receive stable
IDs before model invocation. Their excerpts must be short, secret-safe, and
verified against the captured source. The model cites evidence IDs; it may not
invent paths, line numbers, scanner results, or runtime observations.

## Functional requirements

### FR1: Source verification

The advisor verifies that the checkout's current commit matches the declared
full SHA and that analyzed content is not modified or untracked. Alternatively,
it may materialize the declared commit into an isolated snapshot. It records
safe source provenance without recording a machine-specific checkout path.

### FR2: Closed policy configuration

Policy is loaded from a size-limited, closed schema. Unknown fields, unsupported
categories, invalid limits, and unsafe paths are rejected. Configuration cannot
select arbitrary Python imports or execute control flow.

### FR3: Deterministic evidence collection

Collectors produce typed facts from known repository surfaces. Initial
collectors should favor direct parsing and existing validation tools over model
interpretation.

### FR4: Bounded synthesis

The model receives only approved policy and evidence. Its response must conform
to a closed structured schema and a hard recommendation limit.

### FR5: Evidence validation

Before publication, every cited evidence ID is resolved to a collector record
from the verified snapshot. Unsupported recommendations are rejected or
explicitly marked as insufficient evidence; they are never silently repaired
with fabricated facts.

### FR6: Prioritization

Recommendations are ranked using configured owner priorities, impact,
confidence, and known trade-offs. The product must explain the important
factors behind each rank.

### FR7: Stable lifecycle

The advisor fingerprints recommendations and compares them with a prior report.
Repeated runs distinguish new, unchanged, resolved, and explicitly suppressed
items.

### FR8: Dual report output

Each successful run produces equivalent Markdown and JSON reports. JSON is the
canonical machine-readable record; Markdown is optimized for maintainers.

### FR9: Partial failure

A failed collector is reported without turning missing evidence into a clean
bill of health. The run records which evidence surfaces were and were not
successfully examined.

### FR10: Bounded execution

Runtime enforces time, input-size, collector, model-call, and recommendation
limits. A failed or malformed model response ends safely without publishing an
unvalidated report.

## Non-functional requirements

### Safety and security

- Use read-only GitHub permissions in CI.
- Never require cloud or cluster credentials for the MVP.
- Treat repository content, scanner output, and model output as untrusted.
- Do not log environment values, credentials, unbounded file contents, or raw
  model responses.
- Prevent prompt content found in the target repository from changing tool
  access, policy, or publication rules.
- Keep deterministic publication gates outside the model.

### Reproducibility and provenance

Reports identify the source commit, advisor version, policy version, collector
versions, and model identifier. Re-running against identical inputs should
reproduce deterministic evidence even if narrative wording differs.

### Observability

Runs emit structured lifecycle events for source verification, collector
coverage, synthesis, validation, rejection, comparison, and report completion.
Events contain summaries and identifiers rather than arbitrary source or model
content.

### Testability

Unit and integration tests use repository fixtures, deterministic collector
outputs, and recorded model responses. Tests do not require network, cloud,
cluster, or wall-clock timing.

## MVP acceptance criteria

1. A maintainer can run one command against a verified local fleet checkout.
2. The run completes without AWS or Kubernetes credentials.
3. It produces schema-valid Markdown and JSON reports containing no more than
   the configured recommendation limit.
4. Every published recommendation contains validated repository evidence.
5. Malformed model output, invented evidence, or prompt injection cannot bypass
   the publication gate.
6. A second run can identify unchanged, resolved, and newly introduced
   recommendations.
7. Collector failures are visible in the report's coverage section.
8. All automated tests run deterministically without external systems.

## Success measures

During the initial pilot:

- 100% of published recommendations have valid evidence references;
- zero target-repository or infrastructure mutations occur;
- the report remains within the configured maximum size;
- the owner considers a majority of high-priority recommendations actionable
  or intentionally suppresses them with a recorded reason; and
- repeated reports reduce duplicate review effort rather than recreating the
  same untracked advice.

## Explicit non-goals

- General-purpose infrastructure advice for arbitrary repositories.
- Live AWS, Kubernetes, Prometheus, or Terraform-state inspection.
- Parameter tuning or experimentation against running services.
- Automated source changes, pull requests, merges, deployments, or rollback.
- A plugin marketplace, dynamic imports, arbitrary shell execution, or remote
  tool installation selected by configuration.
- Claims of complete coverage or universal optimality.

## Delivery phases after MVP

Future work must be justified by demonstrated value from the previous phase:

1. Add selected GitHub CI, dependency, and release metadata as read-only input.
2. Add optional read-only runtime observations with explicit credentials and
   provenance boundaries.
3. Generate reviewable patches or draft pull requests with human approval.
4. Introduce narrowly constrained remediation or parameter optimization only
   where rollback and deterministic evaluation exist.

## Open product decisions

- Where maintainers should consume the recurring report.
- Which deterministic collectors form the smallest useful first vertical
  slice.
- How suppression decisions are stored without granting write access to the
  target repository.
- Which model and structured-output interface best fits the first
  implementation.
