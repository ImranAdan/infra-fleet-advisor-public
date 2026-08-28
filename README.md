# Infra Fleet Advisor

Infra Fleet Advisor is a read-only advisor for the
[`infra-fleet-public`](https://github.com/ImranAdan/infra-fleet-public) GitOps
platform.

It periodically inspects the repository at an immutable Git revision, combines
deterministic evidence with bounded AI analysis, and produces a small,
prioritized set of actionable recommendations for keeping the fleet secure,
reliable, current, maintainable, and cost-conscious.

## Product promise

> Turn the desired state and existing validation signals of one GitOps fleet
> into a trustworthy, evidence-backed improvement backlog.

The advisor does not claim that there is one universally optimal platform
configuration. Recommendations are evaluated against the owner's declared
priorities and accepted trade-offs.

## MVP

The first version will:

- review only `infra-fleet-public`;
- analyze a complete repository snapshot identified by a full Git commit SHA;
- run without AWS or Kubernetes credentials;
- reuse deterministic findings from repository-aware collectors;
- use AI only to synthesize, connect, and explain captured evidence;
- return at most a configured number of ranked recommendations;
- produce both a human-readable Markdown report and structured JSON;
- track recommendations as new, unchanged, resolved, or suppressed across
  runs; and
- remain read-only with respect to both the fleet repository and its runtime
  infrastructure.

The MVP will not modify infrastructure, open pull requests, inspect a live
cluster, support arbitrary repositories, or implement autonomous remediation.

## Review flow

```text
load policy and source revision
              ↓
capture repository evidence
              ↓
run deterministic collectors
              ↓
synthesize bounded recommendations
              ↓
validate evidence and safety rules
              ↓
fingerprint, compare, rank, and report
```

Every recommendation must identify concrete evidence, expected impact,
trade-offs, and confidence. Unsupported model output is rejected rather than
published.

## Usage

```bash
export ANTHROPIC_API_KEY=...   # required by the default --synthesizer anthropic

uv run infra-fleet-advisor review \
  --checkout ../infra-fleet-public \
  --sha <full-40-char-commit-sha> \
  --policy path/to/policy.yaml \
  --output-dir ./review-output \
  --prior-report ./previous-run/report.json   # optional, enables lifecycle tracking
```

`--synthesizer stub` swaps the model for a deterministic table-driven
stand-in, which needs no API key and is what the test suite runs on.

If synthesis fails, the run exits non-zero and writes no report. It never
degrades to an empty result, because an empty result would mark every
outstanding finding resolved.

## Status

The `fleet_repository_review` scenario runs end to end: two deterministic
collectors (GitHub Actions workflows, Terraform IAM policies) feeding
model-backed synthesis, validation, and lifecycle tracking.

## Documentation

- [Product research](docs/product-research.md)
- [Product requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [Repository guidance](AGENTS.md)

## License

MIT
