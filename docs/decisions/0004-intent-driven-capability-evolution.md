# PDR 0004: Intent-driven capability evolution

- Status: accepted
- Date: 2026-09-10

## Context

PDR 0003 made Markdown intent authoritative and guaranteed that unsupported
propositions remain visible as `declared_unverified`. That closes the reporting
gap, but it still leaves the owner to notice each missing check and manually
start advisor implementation work.

The product goal is for the owner to maintain intent as the routine input. A
new proposition should either evaluate through an existing trusted capability
or create the work needed to evolve that capability. It must not manufacture a
fleet divergence when no collector can verify one.

## Decision

A merged advisory report is also the ratified source for an advisor-side
capability plan. Deterministic code reloads the current intent and policy,
requires their versions to match the report, and validates a complete,
one-to-one set of proposition evaluations.

Every `declared_unverified` proposition except one deliberately disabled by
policy becomes an active capability-gap action. The action is delivered as a
deduplicated issue in `infra-fleet-advisor-public`, keyed by stable intent
document and proposition identity. Supported, satisfied, or divergent
propositions produce resolution actions for any earlier capability issue. The
publisher never closes or reopens an issue.

Resolution and reactivation are recorded as alternating, bot-authored lifecycle
notes. The publisher reads the complete bounded comment history and adds a note
only when the latest recorded state differs from the current ratified report.
Retries in the same state are no-ops, while active → resolved → active cannot
leave a stale resolution as the latest lifecycle signal.

A capability issue is not a fleet finding. Its inert, bounded body states the
declared position, the validated reason evaluation could not complete, and a
definition of done for reviewed collector and check code. It explicitly
forbids treating the gap as evidence that the fleet violates the intent.

An agent or maintainer may use that issue to propose a normal advisor pull
request containing the missing deterministic collector, check binding, and
tests. The proposal passes the advisor's existing review and CI gates and is
never merged automatically. Once merged, the advisory workflow evaluates the
same intent again. Only concrete conflicting evidence can then cross the
separate, human-ratified report boundary and become a fleet issue.

Natural-language intent remains inert. It cannot install tools, choose an
arbitrary collector, emit executable rules, or authorize repository changes.
This decision automates the creation and lifecycle of capability work; it does
not execute code synthesized from prose.

## Consequences

- Writing intent is sufficient to start either evaluation or advisor evolution.
- The owner does not need to manually translate every unsupported proposition
  into an engineering ticket.
- Novel evidence domains still require code, but an agent can propose that code
  and a human ratifies it through the ordinary pull-request path.
- Fleet issues remain evidence-backed divergences. Capability uncertainty stays
  in the advisor repository and cannot be mistaken for a fleet defect.
- One intent proposition has at most one capability issue across wording and
  version changes; exact markers and labels make retries idempotent, while a
  separate content marker permits bot-owned issue text to track ratified intent.
- Alternating lifecycle markers preserve repeated resolution and reactivation
  transitions without changing human-owned issue state.

## Rejected alternatives

- **Create fleet issues for unverified propositions.** This would present an
  inability to collect evidence as proof that the fleet is wrong.
- **Execute checks generated directly from prose.** This would turn untrusted
  configuration into control flow and bypass the collector registry.
- **Silently leave gaps only in the report.** This preserves honesty but does
  not create a self-evolving delivery loop.
