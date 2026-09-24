# Add a deterministic check

[Documentation index](README.md) · [Contributing](../CONTRIBUTING.md)

A check turns one owner-declared proposition into one of three results:
`satisfied`, `divergent`, or `declared_unverified`. This guide assumes the
proposition already exists in `intent/`, or the owner has asked for it to be
added. A new check does not create or merge fleet work by itself.

## Start with the evidence contract

Write down four things before editing code:

1. **Relevant evidence:** which bounded, tracked files can answer the question?
2. **Divergence fact:** the exact fact values that conflict with the intent.
3. **Unknown cases:** every shape the parser cannot prove. These must make
   collector coverage partial, never silently look healthy.
4. **Stable identity:** the repository object the evidence represents. Prefer a
   resource handle such as kind, namespace and name over a line number.

Extend an existing collector when it already owns that source format. Add a
collector only when the new source has a distinct parser or safety boundary.
Collectors read repository data only; they do not import fleet applications,
run fleet code, invoke infrastructure tools, use the network, or inspect live
services.

## Wire the check

Use this order. It keeps each step testable and avoids hunting through the
repository.

| Step | File | Change |
|---|---|---|
| 1 | `constants.py` | Add the evidence kind. Add a collector ID only for a new collector; bump the collector version whenever its evidence behavior changes. |
| 2 | `collectors/<name>.py` | Emit bounded `Evidence` plus explicit `CollectorCoverage`. Malformed, excluded, untracked, truncated, remote, or unsupported input must make coverage partial or failed. |
| 3 | `concerns.py` | Add one stable concern key and the fallback recommendation wording. The wording describes an established fact; it does not claim live behavior. |
| 4 | `intent_evaluation.py` | Add the check key and one explicit `INTENT_CHECKS` entry mapping the concern, collector, evidence kind, scope, divergence facts, and whether repository evidence can prove satisfaction. |
| 5 | `review.py` | Only for a new collector: call it with tracked paths and exclusions, then add its evidence, coverage, and version to the report. There is no dynamic discovery. |
| 6 | `intent/*.md` | Point the proposition's `Check` field at the registered key. Change intent text only with owner authorization. |

The check definition is the trusted join between inert intent text and code.
Unknown check names remain unverified; Markdown cannot select a Python module or
command.

## Prove both directions

Add focused tests beside the collector and in `test_intent_evaluation.py`:

- a real supported shape produces the expected fact;
- the conflicting shape becomes `divergent`;
- a safe shape becomes `satisfied` only when the collector can prove absence;
- malformed, dynamic, incomplete, excluded, and untracked inputs cannot produce
  false satisfaction;
- duplicate objects, limits, renames, and identity stability are covered where
  they apply.

Add one literal mutation to `drills/fleet-mutations.yaml`. It must change the
real Fleet in a throwaway worktree and make the named proposition diverge. If
the Fleet later moves or rewrites that text, the drill becomes stale and fails
visibly.

Update `docs/status.md` with what the check observes, what it can prove, and
what remains unknown. Update architecture or product requirements only when the
behavioral contract changes.

## Definition of done

```bash
make check
make review
uv run --frozen infra-fleet-advisor drill \
  --checkout ../infra-fleet-public \
  --drills drills/fleet-mutations.yaml \
  --policy policy.yaml --intent-dir intent \
  --output-dir /tmp/infra-fleet-drills
```

In the pull request, include the score printed by `make review`, the drill
result, and the cases that remain unverified. A rising satisfied count is useful
only when new evidence justifies it.
