# PDR 0009: Repository settings evidence

- Status: accepted
- Date: 2026-10-10
- Extends: PDR 0003 intent compilation and divergence delivery

## Owner decision

S-010 declares that the fleet has Dependabot alerts and security-update pull
requests switched on. Repository files cannot show that, so S-010 stayed
`declared_unverified` forever. On 2026-10-10 the fleet was found with both
settings off: the position had diverged for an unknown time and nothing could
see it. The owner wants such positions provable, and treats the advisor's
repository-only boundary as current design to improve rather than a fixed law.

## Decision

1. The advisor may make **one live read**: the fleet repository's security
   settings from the GitHub REST API. The snapshot (schema
   `repository-settings/v2`) holds Dependabot alerts and security updates
   (`vulnerability-alerts`, `automated-security-fixes`), secret scanning and
   push protection (`security_and_analysis` on the repository), and
   default-branch protection (pull requests required, no force-push or
   deletion).
2. The read runs **before** a review, never inside it.
   `infra-fleet-advisor settings-snapshot` writes a closed-schema JSON
   snapshot, and `review --repository-settings` reads that file through
   `repository_settings_collector`. The review stays offline and deterministic
   over its inputs; tests use fixture snapshots and recorded HTTP answers.
3. The token is a separate secret, `FLEET_SETTINGS_READ_TOKEN`: a fine-grained
   token on the fleet repository with **Administration: read** only. The
   issues-only App of PDR 0001 is not widened. The token comes from the
   environment, never argv or logs.
4. Unknown is never healthy. Without a token or permission the snapshot holds
   `null` values and coverage is partial. Without a snapshot, as in the
   pre-merge intent gate, the collector does not run. Either way S-012 is
   `declared_unverified`, never `satisfied`.
5. Three propositions read the snapshot, each able to prove satisfaction
   because the snapshot names its settings outright: **S-012** Dependabot
   alerts and security updates (`repository_security_updates_enabled`),
   **S-013** secret scanning and push protection
   (`repository_secret_protection_enabled`), and **S-014** default-branch
   protection (`default_branch_protected`). S-010 keeps checking the
   committed Dependabot configuration. An unknown value costs every settings
   proof, but a setting known to be off still diverges.
6. Each settings record anchors on the fleet file that documents its control
   (`.github/dependabot.yml`, `SECURITY.md`, `AGENTS.md`), so published issue
   links stay valid. The excerpt says the fact came from the settings
   snapshot.

## Consequences

- Fleet-mutation drills cannot change a repository setting, so S-012 to S-014 are exempt
  from the one-drill-per-position rule. Its fixture tests prove both
  directions and the unknown cases.
- The intent gate is unchanged: it passes no snapshot, so S-012 is
  `collector_not_run` on base and head alike and cannot fail a fleet PR.
- Settings positions extend the one snapshot with a new schema version
  (v2 added S-013 and S-014 on 2026-10-10) rather than adding live reads
  inside the review. Branch protection is owner-only to change, so S-014
  divergence is reported for the owner, never corrected by an agent.

## Rejected alternatives

- **Calling the API inside the review.** That makes reviews depend on the
  network and on the time of the run, and the intent gate would need a
  credential.
- **Adding Administration: read to the issues App.** That widens a token that
  has write access to fleet issues.
- **Marking S-010 satisfied from the configuration alone.** The 2026-10-10
  finding shows that configuration and settings drift apart.
