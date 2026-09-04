# Product requirements

## Product definition

Infra Fleet Advisor is a scheduled, read-only repository advisor that converts
the desired state and validation signals in `infra-fleet-public` into a
prioritized improvement backlog.

It helps the repository owner answer:

> Given the fleet's current intent and accepted constraints, what are the most
> valuable improvements to consider next, and what evidence supports them?

## Primary user

The MVP serves the owner and maintainer of `infra-fleet-public`. It assumes the
user understands GitOps and can decide whether a recommendation should become
work. Broader multi-team or multi-repository use is outside the MVP.

## Desired outcome

Reduce the effort required to inspect the fleet, reconcile scattered signals,
and maintain a credible improvement backlog without granting an AI system
permission to change infrastructure.

## Product principles

- **Evidence before advice:** every recommendation cites captured repository
  evidence.
- **Intent before convention:** configured goals and accepted trade-offs take
  precedence over generic best practices.
- **Deterministic boundaries:** code owns source verification, schema
  validation, limits, lifecycle state, and publication eligibility.
- **AI as an untrusted analyst:** a model may synthesize evidence but cannot
  expand its permissions or publish unsupported claims.
- **Small, useful output:** prioritization is more valuable than exhaustive
  commentary.
- **Read-only by default:** repository and infrastructure mutation require a
  future, explicitly approved product phase.

## MVP inputs

1. A clean, complete checkout of `infra-fleet-public`.
2. The full Git commit SHA expected for that checkout.
3. A versioned advisor policy defining priorities, accepted trade-offs,
   exclusions, and recommendation limits.
4. Deterministic collector results produced during the run.
5. An optional prior recommendation report for lifecycle comparison.

The MVP must not require AWS credentials, Kubernetes credentials, Terraform
state access, or secrets from the target fleet.

## Advisory categories

The initial taxonomy is:

- `security`
- `reliability`
- `cost`
- `lifecycle`
- `maintainability`
- `gitops_correctness`

Categories organize recommendations; they do not create separate autonomous
agents.

## Recommendation contract

Each recommendation must contain:

| Field | Meaning |
| --- | --- |
| `fingerprint` | Stable identifier derived from category, concern, and stable evidence identity. |
| `category` | One value from the configured taxonomy. |
| `priority` | Bounded rank such as critical, high, medium, or low. |
| `title` | Concise actionable summary. |
| `summary` | What should be considered and why. |
| `evidence` | One or more validated evidence IDs resolving to repository-relative facts. |
| `impact` | Expected benefit or avoided risk. |
| `suggested_change` | A bounded proposal, not an automatically executed action. |
| `trade_offs` | Cost, complexity, availability, or maintenance consequences. |
| `confidence` | Bounded score with an explanation of uncertainty. |
| `status` | New, unchanged, resolved, or suppressed. |

Evidence records are created by deterministic collectors and receive stable
IDs before model invocation. Their excerpts must be short, secret-safe, and
verified against the captured source. The model cites evidence IDs; it may not
invent paths, line numbers, scanner results, or runtime observations.

## Functional requirements

### FR1: Source verification

The advisor verifies that the checkout's current commit matches the declared
full SHA and that analyzed content is not modified or untracked. Alternatively,
it may materialize the declared commit into an isolated snapshot. It records
safe source provenance without recording a machine-specific checkout path.

### FR2: Closed policy configuration

Policy is loaded from a size-limited, closed schema. Unknown fields, unsupported
categories, invalid limits, and unsafe paths are rejected. Configuration cannot
select arbitrary Python imports or execute control flow.

### FR3: Deterministic evidence collection

Collectors produce typed facts from known repository surfaces. Initial
collectors should favor direct parsing and existing validation tools over model
interpretation.

### FR4: Bounded synthesis

The model receives only approved policy and evidence. Its response must conform
to a closed structured schema and a hard recommendation limit.

### FR5: Evidence validation

Before publication, every cited evidence ID is resolved to a collector record
from the verified snapshot. Unsupported recommendations are rejected or
explicitly marked as insufficient evidence; they are never silently repaired
with fabricated facts.

### FR6: Prioritization

Recommendations are ranked using configured owner priorities, impact,
confidence, and known trade-offs. The product must explain the important
factors behind each rank.

### FR7: Stable lifecycle

The advisor fingerprints recommendations and compares them with a prior report.
Repeated runs distinguish new, unchanged, resolved, and explicitly suppressed
items.

### FR8: Dual report output

Each successful run produces equivalent Markdown and JSON reports. JSON is the
canonical machine-readable record; Markdown is optimized for maintainers.

### FR9: Partial failure

A failed collector is reported without turning missing evidence into a clean
bill of health. The run records which evidence surfaces were and were not
successfully examined.

### FR10: Bounded execution

Runtime enforces time, input-size, collector, model-call, and recommendation
limits. A failed or malformed model response ends safely without publishing an
unvalidated report.

### FR11: Report delivery

A run may be triggered from CI and deliver its report as a pull request in the
advisor's own repository. This is delivery of the report, not remediation: the
pull request carries `reports/report.json` and `reports/report.md` and nothing
else, and the fleet repository is cloned, analyzed, and left untouched.

The committed report is the baseline the next run compares against, so lifecycle
advances only when an advisory pull request is merged. A run whose findings,
cited evidence, collector coverage, and rejection reasons all match the committed
report proposes nothing, so an unchanged fleet does not accumulate pull requests.

Rejection reasons are part of that comparison deliberately. A synthesizer that
begins refusing candidates has drifted, and that must reach a reviewer even when
the accepted findings are identical — so a rejection-only change does propose a
pull request.

Closing an advisory pull request without merging records a decline at that
report's deterministic material signature. An identical run is not proposed
again until findings, cited evidence, collector coverage, rejection reasons, or
an owner-accepted trade-off changes. Pull-request prose is untrusted; only the
exact versioned signature marker written by the advisor is interpreted.

### FR12: Mechanical remediation

The advisor may propose a code change to the fleet as a pull request, for the
narrow set of concerns fixable without human judgement. It may never merge one.

Patches derive only from a published recommendation and the evidence it cites; a
file containing the same pattern but never cited is out of bounds. The source is
the merged report, so a human has accepted the finding before any patch exists.
Remediation is manually dispatched, defaults to a dry run, and is the only path
holding a fleet write credential.

Concerns requiring judgement — scoping a wildcard IAM policy, for instance — must
not be added to the patcher registry. A confident wrong answer there is a
security regression. See PDR 0002.

### FR13: Fleet issue publication

Merging an advisory report may publish each active, validated recommendation as
an issue in `infra-fleet-public`. The publisher revalidates the merged report
against the current closed policy before acquiring a cross-repository token.
Recommendations that are suppressed, carry an owner-accepted trade-off, cite
invalid evidence, or have a mismatched fingerprint are ineligible.

Issue creation is idempotent per recommendation fingerprint. A partial failure
must be safely retryable without duplicating the issues already created, and a
collision must fail loudly rather than attach advice to an unrelated issue.
When evidence becomes resolved, the publisher may add one deduplicated note but
must never close, reopen, or otherwise change issue state. Issue bodies and
comments are untrusted output surfaces and never become analysis or policy
input. The cross-repository GitHub App token is restricted to one repository and
`issues: write`; it has no permission to read or modify fleet code. See PDR
0001.

### FR14: Fleet decision feedback

A closed advisor-created fleet issue carrying `advisor:wontfix` and exactly one
approved trade-off reason label may propose an accepted trade-off in
`policy.yaml`. Feedback reads only issue number, state, author, and labels; issue
titles, bodies, and comments never become policy, evidence, or model input.

The issue must be attributable to the configured GitHub App, contain exactly one
valid advisor fingerprint, and still map to a current active recommendation. A
decision must not be widened from one finding to an entire concern when multiple
active findings share that concern. In that case, or when listing is incomplete,
the feedback run fails without proposing policy.

The generated policy receives a deterministic new version and is delivered only
as a pull request in the advisor repository. It is never merged automatically.
An exact versioned marker deduplicates both an open proposal and a closed,
declined proposal across unrelated intervening proposals. Pull-request history
is read to a declared bound and fails closed if completeness cannot be proven.
After a policy change, feedback waits for a report produced under that policy
version rather than interpreting a stale report. If the underlying issue
decision is revoked before merge, the workflow withdraws only its own stale
proposal and distinguishes that cancellation from a human decline. A partial
push without a pull request may be recovered only after the reserved branch is
proven to contain one policy-only commit based on merged history.

## Non-functional requirements

### Safety and security

- Use read-only GitHub permissions against fleet code in CI. The
  `fleet-advisory` workflow additionally holds `contents: write` and
  `pull-requests: write` **on this repository only**, solely to propose the
  report it just produced. The separate issue publisher may acquire a GitHub
  App installation token restricted to `issues: write` on the fleet; it has no
  contents or pull-request permission. The feedback workflow downscopes that
  App installation to `issues: read` and holds contents and pull-request write
  only in the advisor repository so it can propose `policy.yaml`. The
  remediation workflow's separate
  write credential remains manual-only and cannot be reached by either path.
- Never require cloud or cluster credentials for the MVP.
- Treat repository content, scanner output, and model output as untrusted.
- Do not log environment values, credentials, unbounded file contents, or raw
  model responses.
- Prevent prompt content found in the target repository from changing tool
  access, policy, or publication rules.
- Keep deterministic publication gates outside the model.

### Reproducibility and provenance

Reports identify the source commit, advisor version, policy version, collector
versions, and model identifier. Re-running against identical inputs should
reproduce deterministic evidence even if narrative wording differs.

### Observability

Runs emit structured lifecycle events for source verification, collector
coverage, synthesis, validation, rejection, comparison, and report completion.
Events contain summaries and identifiers rather than arbitrary source or model
content.

### Testability

Unit and integration tests use repository fixtures, deterministic collector
outputs, and recorded model responses. Tests do not require network, cloud,
cluster, or wall-clock timing.

## MVP acceptance criteria

1. A maintainer can run one command against a verified local fleet checkout.
2. The run completes without AWS or Kubernetes credentials.
3. It produces schema-valid Markdown and JSON reports containing no more than
   the configured recommendation limit.
4. Every published recommendation contains validated repository evidence.
5. Malformed model output, invented evidence, or prompt injection cannot bypass
   the publication gate.
6. A second run can identify unchanged, resolved, and newly introduced
   recommendations.
7. Collector failures are visible in the report's coverage section.
8. All automated tests run deterministically without external systems.
9. A merged report can produce retry-safe, fingerprint-deduplicated issue
   actions without granting the publisher access to fleet code or changing
   issue state.
10. A closed, reason-labelled advisor issue can produce a reviewable,
    deterministic policy pull request without trusting issue prose or changing
    fleet state.

## Success measures

During the initial pilot:

- 100% of published recommendations have valid evidence references;
- zero target-repository or infrastructure mutations occur;
- the report remains within the configured maximum size;
- the owner considers a majority of high-priority recommendations actionable
  or intentionally suppresses them with a recorded reason; and
- repeated reports reduce duplicate review effort rather than recreating the
  same untracked advice.

## Explicit non-goals

- General-purpose infrastructure advice for arbitrary repositories.
- Live AWS, Kubernetes, Prometheus, or Terraform-state inspection.
- Parameter tuning or experimentation against running services.
- Automated merges, deployments, or rollback against the fleet repository, and
  automated source changes applied without human review. Proposing a mechanical
  fix as a pull request against the fleet is in scope under PDR 0002 and FR12;
  merging one is not, and never will be.
- A plugin marketplace, dynamic imports, arbitrary shell execution, or remote
  tool installation selected by configuration.
- Claims of complete coverage or universal optimality.

## Delivery phases after MVP

Future work must be justified by demonstrated value from the previous phase:

1. Add selected GitHub CI, dependency, and release metadata as read-only input.
2. Add optional read-only runtime observations with explicit credentials and
   provenance boundaries.
3. ~~Generate reviewable patches or draft pull requests against the fleet with
   human approval.~~ Brought forward and delivered as FR12; see PDR 0002.
4. Introduce narrowly constrained remediation or parameter optimization only
   where rollback and deterministic evaluation exist.

## Open product decisions

- Which additional deterministic collectors have demonstrated enough value to
  enter the single repository-review scenario.
- Whether and at what cadence the model-backed advisory workflow should run
  automatically, given its external API cost.
