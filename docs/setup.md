# Local setup

[Documentation index](README.md)

The supported target is `ImranAdan/infra-fleet-public`. Changing a checkout path
does not configure a different analysis identity or publication destination.

## Install and run

Requires Git, Python 3.11+, `uv` and Make. Keep the checkouts alongside one another:

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
git clone https://github.com/ImranAdan/infra-fleet-advisor-public.git
cd infra-fleet-advisor-public
make setup
make review
```

`make setup` installs the locked environment and requires internet access.
`make review` uses the deterministic `stub`, resolves the fleet's full HEAD SHA,
verifies a clean checkout and writes `review-output/report.json` and
`review-output/report.md`. It does not change the fleet or the approved report
under `reports/`. Local review uses repository files and makes no model API call.

## Change paths or compare a prior report

```bash
make review FLEET_CHECKOUT=/path/to/infra-fleet-public REVIEW_OUTPUT=/path/to/output
```

Output must stay outside the fleet checkout, including through symlinks. For
explicit inputs and local lifecycle comparison:

```bash
uv run --frozen infra-fleet-advisor review \
  --checkout ../infra-fleet-public \
  --sha <full-40-char-commit-sha> \
  --policy policy.yaml --intent-dir intent \
  --output-dir review-output \
  --prior-report previous-run/report.json
```

Omit `--prior-report` for a first local run. Automation compares only with the
report already merged in advisor main; see [report review](reports.md).

## Optional model wording

`stub` is the default. To opt into model-backed wording, set
`ANTHROPIC_API_KEY` in your environment and add `--synthesizer anthropic` to the
CLI command. This makes a paid external API call. Deterministic checks and
evidence validation still determine the recommendations that can appear.
See [current model support](status.md) for the validation completed so far.

## Troubleshooting

| Symptom | Action |
|---|---|
| `dirty_checkout` | Commit or move local and untracked changes, or use a clean clone. Ignored files are not evidence. |
| `sha_mismatch` | Review the declared full commit in a clean checkout. |
| Unsafe output path | Put the output outside the fleet checkout. |
| Missing API key | Use `stub`, or configure the key for an explicitly selected `anthropic` run. |
| Partial collection or unverified intent | Read [coverage limitations](status.md); do not interpret missing evidence as a healthy fleet. |

For automation, use the [report guide](reports.md),
[fleet publication guide](fleet-publication.md) and [end-to-end runbook](WORKFLOW.md).
For development checks, use [Contributing](../CONTRIBUTING.md).
