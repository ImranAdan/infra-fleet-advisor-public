# Optional mechanical remediation

[Documentation index](README.md)

The normal handoff is a Fleet issue that a coding agent can inspect. The
autonomous path handles only registered deterministic patchers whose output can
be justified directly from merged report evidence.

## Preview a patch

```bash
uv run --frozen infra-fleet-advisor remediate \
  --checkout ../infra-fleet-public \
  --report reports/report.json \
  --policy policy.yaml --intent-dir intent \
  --dry-run
```

Applies only what a merged report already justified, to only the files that
report cited as evidence. A file containing the same pattern but never cited is
out of bounds, and re-running over an already-fixed fleet changes nothing.

## Automatic Fleet proposal

`infra-fleet-public/.github/workflows/advisor-remediation.yml` polls the merged
report after the daily advisory run. Its planning job has read-only permissions,
runs the merged Advisor, and uploads a patch artifact. A separate Fleet-owned
job applies the artifact as data and uses Fleet's `GITHUB_TOKEN` only to open an
opted-in PR. Advisor code never receives a Fleet contents token.

Token-created PRs do not emit ordinary pull-request events, so the Fleet job
explicitly dispatches a read-only validation workflow on the exact generated
branch. That workflow independently limits the diff to the registered transform,
runs gitlint, the template contract, workflow lint, application CI and the
advisor intent gate. `merge_ready.py` then decides the PR. A patch that widens
permissions or reaches any owner-only category stays open.

## Supported patch

Only `trivy_ignore_unfixed` is patchable today. `wildcard_iam_permissions` is
deliberately excluded: scoping it requires knowing which API calls the pipeline
makes, and a confident wrong answer is a security regression.

No supported patch is an expected result when no active ratified concern has a
registered patcher. See [PDR 0008](decisions/0008-autonomous-evidence-loop.md).
