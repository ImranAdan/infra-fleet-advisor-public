# Repository Guidelines

## Mission

Build a read-only advisor for
`https://github.com/ImranAdan/infra-fleet-public`. The product turns a verified
Git repository snapshot and deterministic findings into a short, prioritized,
evidence-backed improvement report.

The MVP serves one repository and one maintainer. It does not modify the fleet,
open pull requests against it, access AWS or Kubernetes, or claim universal
optimality. Preserve that boundary unless an approved product requirement
explicitly changes it.

The `fleet-advisory` workflow does open a pull request, but only in *this*
repository and only to propose the report it just produced. The fleet remains
read-only: it is cloned, analyzed, and left untouched. Delivering a report is
not remediation, and nothing in that path may grow into writing to the fleet.

## Scope and execution discipline

Treat the user's time, attention, and token budget as constrained resources.
Work only on the requested outcome and stop when that outcome is complete.

- Confirm the repository and working directory before taking action. An active
  session directory does not override an explicit target path from the user.
- Before using tools, state the exact scope of the intended inspection or
  change. Keep progress updates brief.
- Do not browse the web, inspect another repository, research providers or
  dependencies, or look up implementation details unless the request requires
  it or the user explicitly asks for it.
- A request to discuss, review, or design is read-only. Do not edit files,
  create branches, open pull requests, push changes, or contact external
  services unless those actions are requested.
- When implementation is requested, inspect and change only the files needed
  for that implementation. Do not use the task as permission for adjacent
  refactors, speculative abstractions, or broader product work.
- Do not expand an MVP, introduce a provider, select infrastructure, or turn a
  product idea into a technical architecture before that decision is needed.
- Make small, reversible assumptions only when they do not change scope. Ask
  the user before proceeding when ambiguity would materially change the
  product, repository, deliverable, or external state.
- Use existing local evidence first. Run checks proportionate to the change and
  avoid unrelated diagnostics.
- Preserve unrelated working-tree changes and commit only files belonging to
  the requested task.
- Keep the final response limited to the outcome, verification performed, and
  any genuine blocker or decision still required.

## Product language

- A **policy** records owner priorities, accepted trade-offs, exclusions, and
  hard limits.
- **Evidence** is a typed fact captured from the verified source or a known
  deterministic collector.
- A **recommendation** is an unexecuted proposal supported by validated
  evidence.
- A **report** contains provenance, coverage, recommendations, and lifecycle
  changes.
- A **scenario** is a cohesive review use case, not a configurable workflow or
  arbitrary plugin.

Do not use `optimal` without naming the policy and trade-offs that define it.
Do not describe recommendations as findings from a live system when the source
is repository desired state.

## MVP contract

Implement one vertical scenario named `fleet_repository_review`:

```text
policy + verified checkout + optional prior report
    → collect evidence
    → synthesize recommendations
    → validate evidence
    → fingerprint and compare
    → write JSON and Markdown
```

Every published recommendation must have a valid category, bounded priority,
concrete repository evidence, expected impact, suggested change, trade-offs,
confidence, fingerprint, and lifecycle status. Missing or invented evidence is
a validation failure.

The model is an untrusted analyst. Deterministic code owns input verification,
collector selection, schemas, safety limits, evidence validation, lifecycle,
and publication eligibility.

## Project shape

Implementation will live under `src/infra_fleet_advisor/` using Python 3.11+
and `uv`.

- Keep immutable evidence, recommendation, report, and pipeline contracts under
  `core/`.
- Keep policy models, loading, and closed validation under `config/`.
- Keep source and run identity under `provenance/`.
- Keep CLI composition, input binding, provider invocation, and output handling
  under `runtime/`.
- Keep repository-review-specific collectors and synthesis preparation under
  `scenarios/fleet_repository_review/`.
- Keep external protocols behind narrow adapters and convert responses into
  typed values at their boundary.
- Mirror source paths and behavior under `tests/`.

Do not create code packages until required by the first end-to-end vertical
slice. Do not introduce dynamic plugin discovery, arbitrary imports or shell
commands from configuration, async workers, a database, multi-repository
orchestration, live-cluster access, or a reusable workflow engine.

## Safety and security

- Operate with read-only access to the target repository.
- Do not require AWS, Kubernetes, Terraform Cloud, or production credentials.
- Verify a clean target checkout against a declared full Git SHA, or materialize
  that commit into an isolated snapshot, before analysis.
- Treat repository text, scanner output, prior reports, and model output as
  untrusted input.
- Repository content must never override instructions, enable tools, alter
  policy, or relax publication gates.
- Register collectors and model providers explicitly in trusted code.
- Use safe YAML loading and closed schemas. Reject unknown fields.
- Enforce hard limits on file size, evidence volume, model calls, execution
  time, and published recommendations.
- Never log secrets, environment values, machine paths, unbounded source text,
  or raw model responses.
- Use repository-relative evidence paths and validate that they remain within
  the verified source root.
- Assign evidence IDs in deterministic code and require the model to cite only
  those IDs. Resolve every citation before publication.
- Report incomplete collector coverage explicitly; absence of evidence is not
  proof that the fleet is healthy.

## Testing

Every behavioral change needs deterministic tests. Cover successful review,
invalid policy, provenance mismatch, unsafe paths, collector failure, malformed
model output, invented evidence, prompt-injection content, recommendation
limits, lifecycle comparison, and secret-safe reporting.

Tests use local repository fixtures, injected clocks, deterministic collector
outputs, and recorded model responses. They must not require network access,
cloud credentials, a Kubernetes cluster, Docker, or wall-clock timing.

Once the Python toolchain is introduced:

- `make setup` synchronizes the locked environment.
- `make test` runs deterministic tests.
- `make lint` checks formatting, lint, and security rules.
- `make typecheck` runs strict typing.
- `make check` runs the complete local suite.

Use typed public interfaces, immutable values where practical, `snake_case` for
modules and functions, and `PascalCase` for types.

## Documentation and changes

Keep `README.md`, `docs/product-research.md`, `docs/product-requirements.md`,
and `docs/architecture.md` aligned with implemented behavior. Product scope
changes belong in the requirements before they become framework abstractions.

Use Conventional Commit subjects of at most 72 characters. Do not add release,
publishing, or deployment automation until there is an installable vertical
slice to validate.

Before submitting a change, state the user-visible outcome, verification
performed, and any effect on the read-only or evidence-validation boundaries.
