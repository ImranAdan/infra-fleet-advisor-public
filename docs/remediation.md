# Optional mechanical remediation

[Documentation index](README.md)

The normal handoff is to select valuable fleet issues and ask a fleet agent to
propose fixes, as described in the [runbook](WORKFLOW.md). This separate optional
path handles only the registered mechanical patcher and is manually dispatched.

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

## Propose a fleet PR

`.github/workflows/fleet-remediation.yml` does the same in CI and opens the pull
request against the fleet. It needs a `FLEET_TOKEN` secret with contents and
pull-requests write there — a GitHub App installation rather than a personal
token — only when opening a proposal. The default dry run reads the public
fleet without this credential. Remediation revalidates the report against the
current policy and intent before deriving any patch.

## Supported patch

Only `trivy_ignore_unfixed` is patchable today. `wildcard_iam_permissions` is
deliberately excluded: scoping it requires knowing which API calls the pipeline
makes, and a confident wrong answer is a security regression.

No supported patch is an expected result when no active ratified concern has
a registered patcher. No workflow merges the proposal. See
[PDR 0002](decisions/0002-mechanical-remediation-of-the-fleet.md).
