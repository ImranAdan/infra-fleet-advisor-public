# Contributing

Infra Fleet Advisor reviews the declared intent of one public Fleet repository
and delivers evidenced recommendations through exact-head gated report PRs. Read the
[overview](README.md), [workflow](docs/WORKFLOW.md) and
[repository guidance](AGENTS.md) before changing its behavior.

## Development setup

Requires Git, Python 3.11+, `uv` and Make.

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
git clone https://github.com/ImranAdan/infra-fleet-advisor-public.git
cd infra-fleet-advisor-public
make setup
make check
```

`make setup` synchronizes `uv.lock`. `make check` runs formatting, lint,
strict typing and the full test suite. See [local setup](docs/setup.md) to run
a review against a clean fleet checkout.

## Find the relevant code

| Directory | Responsibility |
|---|---|
| `src/infra_fleet_advisor/core/` | Evidence, recommendation, report and pipeline contracts |
| `src/infra_fleet_advisor/config/` | Policy and intent loading and validation |
| `src/infra_fleet_advisor/provenance/` | Verified source and run identity |
| `src/infra_fleet_advisor/runtime/` | CLI, input binding and publication adapters |
| `src/infra_fleet_advisor/scenarios/fleet_repository_review/` | Registered collectors, checks and synthesis preparation |
| `tests/` | Deterministic tests mirroring source behavior |
| `intent/` | Owner-declared positions and registered check identifiers |
| `docs/decisions/` | Product decision records |

## Choose a change

Fleet fixes belong in `infra-fleet-public`, where registered mechanical issues
can produce gated PRs and other issues can be picked up by a coding agent.
Advisor changes belong here when they
improve collection, evaluation, report delivery or the documented product.
Unsupported intent is coverage, not an automatically generated development
queue. Discuss a proposed capability against the requirements before adding it.
For an approved proposition, follow [Add a deterministic check](docs/adding-a-check.md)
for the exact evidence, registration, test, drill and documentation path.

Keep changes focused on the requested outcome. Product scope changes need an
owner decision and aligned requirements; a collector or model output cannot
grant new permissions or change policy.

## Validate behavior

Behavioral changes need deterministic tests for the relevant success and
failure paths. Use local Git fixtures, injected clocks and recorded model
responses. Tests must run offline without cloud credentials, a Kubernetes
cluster or live model calls.

```bash
make check
uv run --frozen gitlint --commits origin/main..HEAD
```

PR CI also checks workflow syntax and runs a Trivy filesystem scan.
`tests/fixtures` is excluded from that scan because collectors need deliberately
insecure Terraform fixtures. Workflow or publication changes must preserve the
[security boundaries](SECURITY.md) and test rejection paths as well as success.
Documentation-only changes should check links, commands and consistency with
the implemented behavior.

## Dependency updates

Dependabot checks the locked Python environment and pinned GitHub Actions each
Monday. It groups each ecosystem into one pull request and allows at most one
open version-update PR per ecosystem, keeping review and CI load bounded. Its
commit prefixes and compact group names are chosen to satisfy this repository's
Conventional Commit and 72-character title checks.

The autonomous worker considers a generated update without an opt-in marker or
hand-written Verification section. The merge gate accepts that narrow path only
when GitHub identifies the Dependabot App, every commit is bot-authored and
created by GitHub's canonical committer with a valid `web-flow` signature,
signed metadata declares a patch or minor update, and the diff changes only
dependency versions, lockfiles or same-step
immutable action SHA pins. Visible major-version jumps and unsupported diff
records fail closed. It still requires
the normal Quality, Advisor Gates, review and exact-head merge checks. A failing
grouped update should be repaired or narrowed rather than merged around a gate.
PR-body metadata cannot opt a rejected bot update into the ordinary agent path;
recreate an intentionally reviewed major update on an agent branch.
Quality applies every title and commit-subject rule to Dependabot updates.
Commit-body line length is not enforced for any contributor: package lists,
immutable URLs and useful review context should not be rewrapped merely to
satisfy an aesthetic CI rule.

## Propose a pull request

- Use a Conventional Commit subject of at most 72 characters.
- Explain the concrete problem and resulting behavior.
- Include the checks performed and any material limitation.
- Keep README navigation and the relevant guide aligned with the change.
- Update [requirements](docs/product-requirements.md) and
  [architecture](docs/architecture.md) when product behavior changes.
- Verify review claims against current code; explain what changed or why a
  finding does not apply.

Report proposals change only `reports/report.json` and `reports/report.md`.
Keep implementation or documentation edits in separate PRs so the report merge
remains a clear decision record for Fleet issue creation. Required checks and
the merge gate still apply to Fleet fix proposals.

## Automated merge decisions

Repository agents use the local merge gate after CI and review are complete.
The policy lets deterministic exact-head evidence decide reversible categories.
It also requires a successful `Advisor Gates` check whose Actions run comes
from the declared workflow and exact head. That isolated job contains the
drills, ratchet, workflow lint and security scan; a missing or same-name
substitute fails closed. Changes to durable authority, access, migrations,
declared intent and the merge system remain with the repository owner.

The pull request template opts same-repository branches into the autonomous
worker. Keep the marker to merge when the gate reaches `READY`; remove it to
hold the PR. Generated report PRs opt in. Verified Dependabot branches are
considered without the marker, but the gate's closed version-only proof remains
mandatory. Quality, external review completion and the report workflow wake the
worker; a six-hour schedule recovers missed events.

This default path needs no model or API key. The Anthropic transport remains
available only if a future policy category explicitly uses the `judge` decider.
`Advisor Gates`, including its ratchet, retains its veto over every approval
path. See the
[merge-gate guide](.claude/skills/merge-gate/SKILL.md) for verdicts and the
exact-head merge command.

For vulnerability reports, follow [Security](SECURITY.md).
