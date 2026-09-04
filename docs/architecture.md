# Architecture

## Architectural intent

The MVP is a bounded, read-only analysis pipeline for one known GitOps
repository. It is not a general agent platform and does not need an autonomous
plan-act loop because it cannot mutate the target system.

```text
AdvisorPolicy ───────────────────────────┐
                                        │
Verified fleet snapshot → collectors → evidence set
                                        │
                                        ├→ synthesis → validation
Prior report ───────────────────────────┘                  │
                                                           ↓
                                             JSON + Markdown report
                                                           │ merged
                                                           ↓
                                      revalidated issue plan → fleet issues
                                                                    │
                                                   closed + typed reason labels
                                                                    ↓
                                      validated feedback plan → policy PR
```

## Domain boundaries

### `config`

Owns the closed advisor-policy contract, safe loading, defaults, and validation.
Policy expresses priorities and constraints; it does not select arbitrary code
or contain workflow logic.

### `provenance`

Verifies and records the fleet source revision and the identities of policy,
collectors, advisor, and model used for a run. Private machine paths are kept
separate from public report provenance.

### `core`

Owns immutable evidence and recommendation models, validation, fingerprints,
lifecycle comparison, ranking inputs, report outcomes, and bounded pipeline
coordination. It remains independent of GitHub, model SDKs, and filesystem
layout.

### `scenarios`

Contains the single `fleet_repository_review` vertical slice. The scenario
selects known collectors, prepares approved evidence for synthesis, and defines
the advisory taxonomy. A second scenario must represent a real product need,
not a speculative extension point.

### `runtime`

Binds a verified checkout, policy, prior report, model client, output streams,
explicit scenario provider, and external publication plans for one invocation.
It owns CLI composition, safe output handling, and GitHub adapter inputs but not
recommendation semantics.

## Supporting adapters

Repository parsers, subprocess-backed scanners, Git verification, model
clients, and report serializers sit at explicit boundaries. Their outputs are
converted into typed domain values before entering the core.

The first implementation should add only the adapters needed by one useful
end-to-end review. Do not introduce dynamic plugin discovery, an arbitrary
command runner, a database, async workers, or multi-repository orchestration.

## Trust boundaries

### Target repository

Repository contents are untrusted input, even though the initial target is
public and owned by the same maintainer. Text found in source files cannot alter
advisor policy, tool permissions, system prompts, or publication rules.

### Deterministic collectors

Collectors are explicitly registered in code. They have read-only access to the
verified snapshot and return closed evidence types. Configuration cannot supply
commands or import paths.

Collectors also declare the identity components used to derive each evidence
ID. Terraform IAM evidence uses its root-module directory and stable resource
address without the `.tf` filename, so moving a resource between files in the
same module preserves lifecycle identity without conflating separate root
modules. GitHub Actions evidence remains keyed by workflow path and step locator
because steps without explicit IDs have no stable resource handle; file moves
or inserted steps can therefore still produce a one-time lifecycle change.

### Model

The model receives a bounded projection of policy and evidence. It cannot read
files, run tools, publish reports, or request broader access. Its structured
response is untrusted until validated.

### Publication

Deterministic code checks schema, evidence existence, category, limits, and
secret-safe fields. Only validated recommendations reach JSON or Markdown
output.

Report delivery derives a versioned signature from deterministic material only:
recommendation fingerprints and lifecycle, cited evidence records including
repository locations, collector coverage records, rejection reasons, and
accepted trade-offs. Model prose, ranking, and run timestamps are excluded. The
signature is recorded as an inert marker in an advisory pull request. If the
latest closed, unmerged advisory pull request has the same exact marker,
delivery treats that state as declined and does not re-propose it; arbitrary
pull-request prose never enters analysis or policy.

Fleet issue publication is a second publication boundary after report merge.
Deterministic code reloads the report under the current policy, recomputes every
fingerprint, resolves every citation, validates evidence support and secret-safe
fields, and emits a bounded issue plan. A workflow adapter consumes only that
plan. It uses an installation token limited to `issues: write`, deduplicates on a
per-fingerprint label and body marker, and never changes issue state. Resolution
means “no longer detected” and produces an idempotent note for human review, not
automatic closure.

Fleet decision feedback is a third deterministic boundary. The GitHub adapter
projects fleet issues into number, state, author, and label sets; title, body,
and comments are discarded at the boundary. Trusted code accepts only closed,
App-authored advisor issues with one fingerprint and one reason from a static
vocabulary. It resolves the fingerprint against the revalidated current report
and refuses to widen one issue into a concern-level policy decision when that
concern has multiple active findings. The resulting plan changes only
`policy.yaml`, assigns a deterministic new policy version, and is proposed as a
human-reviewed pull request in the advisor repository. A fleet token with
`issues: read` cannot change the fleet. An open workflow-authored proposal is
withdrawn if its source labels or closed state are revoked; a typed cancellation
marker prevents that closure from becoming a decline record.

## Run lifecycle

1. Load and validate advisor policy.
2. Verify or materialize a clean target snapshot at its declared full Git SHA.
3. Execute the explicitly configured collector set within hard bounds.
4. Record collector coverage and failures.
5. Assign stable evidence IDs and project approved evidence into the synthesis
   request.
6. Parse the model response into a closed recommendation schema.
7. Resolve every cited evidence ID against the captured evidence set.
8. Compute stable fingerprints and compare with the prior report.
9. Apply deterministic output limits and ordering rules.
10. Write equivalent JSON and Markdown reports.

## Initial implementation shape

When code is introduced, use a small Python 3.11+ package managed by `uv`:

```text
src/infra_fleet_advisor/
├── config/
├── core/
├── provenance/
├── runtime/
└── scenarios/
    └── fleet_repository_review/
```

Mirror behavior under `tests/`. Delay exact modules until the first vertical
slice establishes concrete responsibilities.
