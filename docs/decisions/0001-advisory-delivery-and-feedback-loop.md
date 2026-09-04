# PDR 0001: Advisory delivery and the fleet feedback loop

- Status: accepted
- Date: 2026-08-28
- Supersedes: parts of `docs/product-requirements.md` (noted per decision)

## Context

The advisor produces an evidence-backed report and delivers it as a pull request
in this repository. That loop has no closure: recommendations are informational,
and nothing carries a finding into the fleet's own workflow. A finding becomes
`resolved` only when someone independently fixes the fleet and a later run stops
seeing the evidence.

This record captures the decisions taken on how that loop closes, and the gaps
found while working through it.

## The intended flow

```
advisor run → report → PR in this repo → human merges or closes
     merge  → baseline advances → issues raised in the fleet
     close  → decline recorded, not re-proposed
     fleet  → wontfix label → PR against policy.yaml here → human merges
```

Findings flow outward as issues. Decisions flow back as policy changes. Both
directions are human-gated.

## Decisions

### D1: A closed advisory pull request is the decline record

Merging advances the lifecycle baseline. Closing previously recorded nothing, so
the next run re-proposed an identical report indefinitely — the decision maker
was punished for saying no.

A run now checks closed advisory pull requests as well as open ones, and treats a
closed one as "declined at this signature". It stops re-proposing until the
signature changes.

Accepted weakness: this records *that* a report was declined, not *why*. Per-finding
rationale still belongs in `policy.yaml` as an accepted trade-off.

### D2: Cross-repo writes go through a GitHub App

Raising issues in the fleet needs `issues: write` there. `GITHUB_TOKEN` is scoped
to this repository, so this requires a GitHub App scoped to issues only, installed
on the fleet. An App rather than a PAT: auditable, rotatable, not tied to a person,
and structurally unable to touch code.

**This supersedes** the requirement that the advisor "holds no credential for the
fleet beyond public read, and no workflow may acquire one." The boundary that
remains is narrower and still meaningful: no credential that can modify fleet
*code*.

### D3: Evidence identity must survive refactoring, and issues are never auto-closed

`assign_evidence_id` hashes `source_path|locator`. Both are positional, so a file
rename or an inserted workflow step changes the fingerprint: the old finding reports
`resolved` and an identical new one reports `new`. Today that is a wrong count. Once
issues are automated it closes a real ticket and opens a duplicate.

Two changes, the second load-bearing:

1. Drop `source_path` from the identity hash where the locator already carries a
   stable resource address (Terraform's `aws_iam_policy.github_actions` does).
   GitHub Actions has no equivalent handle — step indices shift — so this is a
   partial fix.
2. The advisor never closes an issue. It comments "no longer detected as of
   `<sha>`" and a human closes it.

(2) matters independently of (1), because `resolved` means "the pattern is gone",
not "the risk is gone". Expanding `eks:*` into every `eks:` action satisfies the
collector and changes nothing about blast radius.

This is a refactor of evidence ID assignment and both collectors, and it breaks
existing fingerprints: current findings reissue once as new.

### D4: Git history stores accepted reports; closed PRs store declined ones

Actions artifacts were considered as the report store and rejected for accepted
reports. Every merged advisory PR is already a commit — `git log -- reports/report.json`
is permanent, queryable, and linked to its PR through the merge commit. Artifacts
expire (90 days by default) and are retrieved as zips.

Declined reports are preserved by their closed pull requests, which D1 keeps
around. Artifacts are therefore reserved for debugging failed runs.

### D5: Issue creation is keyed on fingerprint and fails loudly

The fingerprint is the dedupe key, carried as a label or body marker and searched
before creating. It is checked per issue, not per run — a workflow that dies after
five of eight issues must not duplicate those five on retry.

If issue creation fails after the report has merged, the baseline has already
advanced: those findings would be `unchanged` forever and never ticketed. That
failure must be loud and the workflow re-runnable.

### D6: The feedback loop reads labels, not prose, and lands in policy

Only declines need a mechanism. A fixed finding needs none — the evidence
disappears and the next run resolves it.

- **Labels and issue state only.** Issue comments are untrusted input in the same
  class as repository text and model output. Feeding them to the synthesizer is a
  direct injection path. Labels are a closed vocabulary that can be validated.
- **Live issue state never drives a report.** A report is a function of (fleet SHA,
  policy, prior report). That is what makes it reproducible and is the basis of the
  provenance story. A `wontfix` label instead opens a pull request here against
  `policy.yaml`, adding the accepted trade-off and its rationale. A human merges it,
  and the decision becomes declared policy.
- **`wontfix` is not `invalid`.** A won't-fix is an accepted trade-off and stays
  visible in the report with its rationale. An invalid finding means the collector
  or model was wrong; that is a defect against the advisor, and suppressing it
  would hide a real bug.

### D7: Two more synthesizers, selected statically — deferred

The `Synthesizer` protocol already supports alternatives, and validation treats
every synthesizer as equally untrusted — a weaker model degrades output quality
without weakening any safety guarantee.

- **A template synthesizer.** `StubSynthesizer` promoted from test stand-in to a
  supported tier for users who cannot or will not run an LLM. This is naming and
  template-quality work, not new architecture.
- **A local/bring-your-own-model synthesizer.** An OpenAI-compatible endpoint
  (Ollama, vLLM) configured by base URL and model name.

Local models honour JSON schemas unreliably. The current parse path raises on any
malformed candidate and kills the run, which is right under Anthropic's strict
schema enforcement and too brittle for a small local model. It needs to drop
individual malformed candidates while still failing loudly when *every* candidate
is malformed — silently returning nothing would mark every finding resolved.

Selection stays a static registry chosen by `--synthesizer`. Loading a customer's
own synthesizer class is dynamic import selected by configuration, which
`docs/product-requirements.md` lists as an explicit non-goal. Extension is by
forking. Genuine third-party extension would require revisiting that non-goal
deliberately, as was done for the pull-request boundary.

### D8: A model API key is not a prerequisite for the delivery work

The pipeline runs end to end on the template synthesizer. Decisions D1–D6 can be
built and verified without any model credential.

The caveat is content quality: an issue raised from templated text is adequate for
`trivy_ignore_unfixed` and weak for `wildcard_iam_permissions`, where the specific
actions granted are the entire value. Verify the model path before issues carry
real weight with fleet maintainers.

## Build order

1. Surface rejection reasons — currently computed and discarded at `review.py:109`
2. Stable evidence identity, and never auto-close (D3)
3. Closed-PR-as-decline (D1)
4. GitHub App and issue creation with fingerprint dedupe (D2, D5)
5. `wontfix` label to policy pull request (D6)

Implementation status: steps 1–5 are delivered. The issue publisher derives a
bounded plan from the merged report, uses a one-repository GitHub App token with
only `issues: write`, and deduplicates before every create so partial runs are
retry-safe. The feedback workflow reads only issue identity, state, App author,
and a closed reason-label vocabulary through an `issues: read` token. It maps a
decision back to one current fingerprint, refuses ambiguous concern-level
widening, and proposes a deterministically versioned `policy.yaml` for human
review. A human closing that pull request declines its exact feedback signature;
if the fleet decision is revoked first, the workflow withdraws its own proposal
with a distinct cancellation marker. Decline signatures remain effective across
intervening proposals within a bounded, complete branch history, and partial
branch pushes can recover only after a policy-only ancestry proof.

Steps 1–3 need no new credentials. Step 4 is where the App arrives.

### Deferred

D7 is deferred in full. Both synthesizers are speculative — no user has asked for
either — and the `Synthesizer` protocol makes each a drop-in whenever one does.
Deferring costs nothing now and avoids naming and template-quality work with no
consumer.

Verifying the model path against the real API is off the critical path, per D8.
Do it before issues carry weight with fleet maintainers, not before building the
delivery mechanics.

## Known gaps not yet resolved

- GitHub Actions evidence has no stable identity handle; step reordering will
  still churn fingerprints after D3.
- `resolved` remains satisfiable without reducing risk. Never auto-closing limits
  the damage; it does not fix the semantics.
- Decision rationale is split: D1 records declines at report granularity, while
  per-finding rationale lives in `policy.yaml`.
- Naming for the promoted template synthesizer is undecided.
