---
name: blast-radius
description: Find what an advisor change could break beyond its diff (report consumers, evidence identities, the fleet's pinned gate) and prove the one fact it is safe because of by running real code. Use for "what could this break", before merging a collector, check, renderer, report or CLI change, or when reviewing a small diff you do not trust.
---

# Blast radius

Listing callers is not the job; `git grep` does that in a second. The job is
the breakage grep cannot show you. Adapted from `blast-radius` in
[pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT).

## How sure are you

For each fact the change's safety depends on, push it as far down this ladder
as is cheap, and say where it stopped:

1. You said so. Worthless on its own.
2. You pointed at the line: a real `file:line`, or the upstream source.
3. You walked the failure case step by step and it does not reach.
4. You ran it: a test or script calls the real code and fails loudly if you
   are wrong.
5. You reproduced it against the real fleet (`verify-advisor`).

## Where grep stops in this repository

- **The report is an interface.** `report.json` is read by the intent gate,
  the ratchet guard, the issue publisher, `report-readiness`, and the fleet's
  Grafana dashboard, which reads `reports/report.json` on `main` with JSONata
  over `intent_evaluations`. Renaming a field or status breaks readers in
  another repository.
- **Evidence identities.** Issue deduplication and lifecycle comparison key on
  `evidence_id`. A changed `identity_parts` or `source_path` reopens or
  orphans fleet issues.
- **The fleet's pinned gate.** The fleet runs this repository's gate at a
  pinned commit. A change it needs, such as a renderer that understands a new
  kustomize field, must merge here and be pinned there before the fleet change
  can pass.
- **Fail-closed paths.** A collector that newly fails closed turns satisfied
  positions into unknown ones; one that stops failing closed can turn unknown
  into a false result. Both move the ratchet and the gate.
- **Drills match fleet text.** A drill's `find` is literal fleet text; a
  harmless fleet edit can make it stale.
- **Substitution semantics.** The renderer mimics Flux (text substitution,
  escapes, defaults, runtime sources left unknown). Check a change against
  Flux's documented behavior, not intuition.

## Steps

1. Read the change: the diff, and what it now does differently that the diff
   does not spell out.
2. Find the one fact it is safe because of.
3. Look where grep stops, using the list above.
4. Judge each risk: how likely, how bad. Keep the confirmed ones; list the
   cleared ones separately.
5. Prove the one fact: a focused test, the ratchet guard on the real fleet, or
   the gate on a fleet change. Paste what happened.

## What to hand back

- **What it does**, including the part that is not obvious.
- **The one fact it is safe because of**, the ladder step reached, and the
  proof. Say `unproven` if you could not prove it.
- **Risks**, each with `file:line`, likelihood, cost and how to check.
- **Cleared**: what you checked and why it is fine.
- **Before you merge**: the cheapest check that catches the real bug.
