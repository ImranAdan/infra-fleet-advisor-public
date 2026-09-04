# PDR 0003: Intent compilation and guaranteed divergence delivery

- Status: accepted
- Date: 2026-09-04

## Context

The advisor previously selected concerns from whatever evidence collectors
found. The owner's intent existed as prose, but no runtime input connected a
declared position to evidence, evaluation, recommendations, or fleet issues.
Adding another intent document therefore changed nothing.

Model synthesis also created a delivery gap. Deterministic evidence could show
a concern while an empty or differently shaped model response omitted the work.
That conflicts with the mission: every evidenced divergence must reach a human,
while propositions outside current collector coverage must remain visible as
unverified.

## Decision

Intent is a bounded Markdown catalog and the human-authored document is the
runtime source of truth. A small structural contract fixes document metadata,
proposition headings, and optional evaluation metadata; the content under each
`Intent` heading remains free-form Markdown. Each proposition has stable document
and proposition identities, a category, an inert statement, and optional
priority and static-check metadata. The canonical catalog digest is report
provenance and part of its material signature.

Check identifiers resolve only through a trusted in-code registry. A registry
entry fixes the collector, evidence kind, support predicate, repository scope,
concern, and recommendation template. Intent cannot import code, choose tools,
run commands, or create a check from natural language.

Each proposition evaluates to exactly one state:

- `satisfied` when complete, relevant evidence can prove the declared state;
- `divergent` when concrete evidence conflicts with it; or
- `declared_unverified` when the check is absent or unknown, its category is
  disabled, its collector did not complete, or available evidence cannot prove
  the proposition.

A divergent proposition creates one required recommendation backed by its full
conflicting evidence set. A model remains an optional analyst of wording. Its
candidate replaces the trusted template only if deterministic validation gives
it the exact compiled fingerprint; otherwise the fallback survives. Model
omission can no longer suppress declared work, and model output cannot create a
new work identity.

Fleet issue planning reloads the current intent catalog, requires its digest to
match the merged report, and includes the originating intent document and
proposition in the issue action and body.

## Consequences

Adding a Markdown intent document always changes the report: propositions become
evaluated declarations immediately. It does not guarantee automatic support.
New verification capability still requires reviewed collector and registry
code; until then the gap is explicit rather than guessed.

The policy recommendation limit remains a hard safety bound. If the number of
required divergent propositions exceeds it, the run fails rather than silently
dropping owner-declared work. The owner must raise the bound or reduce active
scope deliberately.

The initial security catalog maps only the OIDC-only CI credential proposition
and the persistent IAM wildcard proposition. The remaining declarations are
reported as unverified. A Trivy mapping exists in test fixtures and the trusted
registry, but is not attached to the production security proposition because
the current collector cannot prove that proposition's full fixed-vulnerability
and documented-exception semantics.

## Deferred

- Additional categories and checks enter the same repository-review scenario
  only when a deterministic evidence surface exists.
- Generating check implementations from natural-language intent is out of
  scope; it would turn untrusted configuration into control flow.
- End-to-end agent implementation of fleet issues belongs in the fleet
  repository. This advisor's contract ends at a human-ratified issue or a
  narrowly mechanical proposed pull request; it never merges fleet changes.
