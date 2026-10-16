# Infra Fleet Advisor report

- Source: `infra-fleet-public` @ `a0dd1178159dd04bbb2449c6019cb6b77074b1e0`
- Advisor version: `0.1.0` · Policy version: `1.1`
- Model: `stub-synthesizer-v1` · Run started: `2026-10-16T09:05:12.232133+00:00`
- Intent catalog: `intent-md-v1:36a055bb6c6b9968dfb5dafe83d5d01b0e409bbb99d30eff038c8edb43bb7f7b`
- Lifecycle: 0 new, 1 unchanged, 10 resolved, 0 suppressed (0 rejected)

## Collector coverage

- `github_actions_workflow_collector`: ok (20 evidence)
- `terraform_iam_collector`: ok (0 evidence)
- `terraform_cost_collector`: ok (7 evidence)
- `kubernetes_deployment_collector`: ok (6 evidence)
- `kubernetes_security_collector`: ok (9 evidence)
- `fleet_lifecycle_collector`: ok (3 evidence)
- `dependency_update_collector`: ok (11 evidence)
- `application_config_collector`: ok (1 evidence)
- `application_contract_collector`: partial (1 evidence) — an on-demand application launcher is declared; its run-time constraints are outside repository evidence
- `documentation_link_collector`: ok (56 evidence)
- `agent_rules_collector`: ok (2 evidence)
- `platform_collector`: ok (18 evidence)
- `repository_settings_collector`: partial (0 evidence) — repository settings unknown (dependabot_alerts, security_updates, secret_scanning, push_protection, default_branch_protected): no settings token was provided

## Intent evaluation

**Coverage:** 37 of 37 positions have a check — 16 satisfied, 1 divergent, 20 checked but unproven; 0 declared without a check.

- `declared_unverified` `infra_fleet_public_cost/C-001` — Staging application worker capacity scales to zero outside an owner-defined
  usage window. A delayed startup of up to 30 minutes is acceptable when it avoids
  paying for otherwise idle compute.
  - Category: `cost` · Priority: `high` · Check: `staging_capacity_released_on_schedule` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_cost/C-002` — Every non-production EKS worker group declares demand-driven scaling with a zero
  minimum where its workloads permit it and an explicit bounded maximum. Any
  always-on baseline must name the workload that requires it.
  - Category: `cost` · Priority: `high` · Check: `worker_groups_demand_scaled` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_cost/C-003` — Every staging CloudWatch log group managed by the fleet has an explicit
  retention period of no more than 30 days. Longer retention requires a documented
  operational or compliance reason.
  - Category: `cost` · Priority: `medium` · Check: `staging_log_retention_bounded` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_cost/C-004` — Every ECR repository managed by the fleet has a lifecycle policy that removes
  untagged images and bounds the number or age of retained images. Images retained
  for rollback or audit have an explicit exception.
  - Category: `cost` · Priority: `medium` · Check: `ecr_lifecycle_bounded` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_cost/C-005` — Terraform-managed AWS resources that support tagging declare consistent
  environment, service, and owner tags so billed usage can be attributed. Any
  resource that cannot carry these tags is reported as an explicit coverage gap.
  - Category: `cost` · Priority: `medium` · Check: `aws_cost_allocation_tags` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_cost/C-006` — The local profile fits a laptop: the CPU and memory requests it declares in Git,
  summed over workloads and HelmRelease values, stay within 1 CPU and 2 GiB. A
  component that needs more is a deliberate change to this budget.
  
  Evidence: \[local profile\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/clusters/local)
  
  Caveat: chart defaults are not rendered, so the declared sum is a lower bound
  and the check can show the budget exceeded, never met.
  - Category: `cost` · Priority: `medium` · Check: `local_footprint_within_budget` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_cost/C-007` — Prometheus keeps metrics for a bounded time and size, so telemetry never grows
  until it fills a node's disk.
  
  Evidence: \[kube-prometheus-stack values\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/infrastructure/observability/kube-prometheus-stack.yaml)
  - Category: `cost` · Priority: `medium` · Check: `metrics_retention_bounded` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_maintainability/M-001` — Every supported deployment profile exposes the same three lifecycle commands:
  \`./fleet setup --profile \<profile\>\` prepares and validates the target,
  \`./fleet up --profile \<profile\>\` brings the platform to a ready state, and
  \`./fleet down --profile \<profile\>\` removes the resources owned by that profile.
  Each phase is safe to repeat and resume after partial failure, reports its target
  before mutation, and ends with either a clear success state or an actionable
  failure. Successful setup and startup print the next command needed by the
  adopter.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_profiles_expose_lifecycle` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_maintainability/M-002` — From a clean clone on a supported workstation, an adopter can prepare the
  pinned local toolchain with one \`./fleet setup --profile local\` command, start
  the complete local platform with one \`./fleet up --profile local\` command, and
  remove every local resource owned by that checkout with one
  \`./fleet down --profile local\` command. The local path requires no AWS account,
  HCP Terraform account, GitHub write credential, repository edit, or mutation of
  the user's default Kubernetes context.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_local_first_use` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_maintainability/M-003` — An adopter with an AWS account, an HCP Terraform organization, and a GitHub
  repository supplies account-specific configuration through a non-committed
  input file and existing local AWS, HCP Terraform, and GitHub CLI sessions. One
  \`./fleet setup --profile aws-staging\` command validates the selected account,
  region, organization, repository, and protected environment; configures the
  required repository and HCP Terraform settings; and bootstraps the permanent
  AWS foundation used for GitHub OIDC deployment. It never stores long-lived AWS
  access keys in GitHub.
  
  After setup, one \`./fleet up --profile aws-staging\` command deploys the reviewed
  staging platform into that account through the protected GitHub environment and
  short-lived AWS credentials. One \`./fleet down --profile aws-staging\` command
  removes billable staging resources, preserves the permanent bootstrap foundation,
  requires explicit confirmation of the target, and reports any resource it could
  not remove. Destroying permanent bootstrap resources remains a separate,
  deliberate operation.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_aws_onboarding` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_maintainability/M-004` — The platform runs whichever application its contract,
  \`k8s/fleet-app/fleet-app.yaml\`, selects, and names none of its own. Routing,
  progressive delivery, autoscaling, network policy, admission, the local build
  and the acceptance test read the application from that contract, so replacing
  the application is a contract change rather than a platform migration. At
  least two applications ship contracts, so the swap stays exercised rather than
  theoretical. Per-application AWS resources (its ECR repository, release
  workflow and secrets) are outside this position.
  
  Locally, the application dashboard may also run any other contracted
  application on demand beside the selected one. Whenever it does, a launched
  application is deployed from the same Git revision with the same platform
  services, filled from its own contract, under an identity limited to application
  workloads in \`applications\` and app-owned Grafana dashboard ConfigMaps in
  \`observability\`, and stopping it removes that stack. The control API is isolated
  from other pods. Launching adds no platform code that names an application.
  - Category: `maintainability` · Priority: `medium` · Check: `fleet_application_swappable` · Reason: `collector_incomplete`
- `satisfied` `infra_fleet_public_maintainability/M-005` — An agent merges the pull requests it raises in this fleet without waiting for
  the owner or calling a paid model whenever evidence alone decides. The Advisor
  may also propose registered mechanical Fleet fixes through this lane. Evidence
  decides when every GitHub Actions check on the exact head
  commit passes, including the advisor's gate for that repository (the intent
  gate for the fleet, the ratchet guard for the advisor), no review thread is
  unresolved, and the pull request records its verification. The advisor is the
  captain: a merge that its gate would reject never happens.
  
  Autonomy stops where a mistake is hard to see or hard to undo. The owner still
  decides changes to credentials, added or widened permissions, IAM, permanent
  infrastructure, and the merge system itself. The merge system includes the
  workflows, scripts and code that produce the advisor's gate checks, so no
  change can approve itself by weakening its own gate.
  
  Missing, running or failed evidence means no approval; the system never
  approves by default or by timeout. Anything merged without the owner must be
  reversible by reverting its merge commit, without a state, schema or data
  migration. Routine pull requests opt in through a visible marker. A trusted
  default-branch worker runs the same exact-head merge gate after CI and on a
  scheduled retry; removing the marker holds the pull request.
  
  Caveat: a complete workflow scan proves whether the Fleet declares the closed
  worker workflow, permissions and protected gate invocation. Excluded, malformed
  or truncated workflow input leaves the position unknown. The check does not
  prove GitHub service availability or that an external coding-agent runtime is
  continuously running. The decision policy remains the authority for categories
  that require the owner.
  - Category: `maintainability` · Priority: `high` · Check: `fleet_autonomous_merge` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_maintainability/M-006` — Agents carry work from a finding to a merged pull request without pausing for
  the owner. Only the owner-only actions listed in the fleet's \`AGENTS.md\`
  (credentials, widened permissions, branch protection and Actions policy,
  deletion, and approval of merge-authority changes) reach the owner, and they
  arrive as a \*\*Decision needed\*\* issue while other work continues, never as a
  stalled session.
  
  Caveat: whether an agent paused is not visible in repository evidence, so the
  check cannot prove this position. It catches the regression that would make
  pausing the rule: the fleet's \`AGENTS.md\` losing its Autonomy grant or
  Owner-only list, or \`.github/pull\_request\_template.md\` losing the
  \`\<!-- autonomous-merge --\>\` opt-in. The rest is enforced through the agent
  rules and the merge gate, and reviewed by the owner.
  - Category: `maintainability` · Priority: `medium` · Check: `fleet_agent_autonomy_declared` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_maintainability/M-007` — Every change that alters behaviour updates the documentation describing it in
  the same pull request. Docs never point at files, paths or commands that no
  longer exist.
  
  Caveat: the check proves the mechanical part, that every relative link in
  tracked Markdown resolves to a tracked file or directory. Whether prose still
  describes current behaviour remains a review responsibility.
  - Category: `maintainability` · Priority: `medium` · Check: `documentation_links_resolve` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_maintainability/M-008` — Every application publish workflow (\`.github/workflows/\*-publish.yml\`) feeds
  the DORA metrics workflow, so a new application's deployments are counted from
  its first release.
  
  Evidence: \[DORA metrics workflow\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/.github/workflows/dora-metrics.yml)
  - Category: `maintainability` · Priority: `medium` · Check: `publish_workflows_feed_dora` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_maintainability/M-009` — Every platform manifest under \`k8s/\` is applied by at least one deployment
  profile, so no reviewed change edits a file that nothing deploys. Flux's
  bootstrap (\`k8s/flux-system/\`) and the on-demand application catalog
  (\`k8s/applications/\<app\>/\`) are outside this position.
  
  Evidence: \[deployment profiles\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/clusters)
  - Category: `maintainability` · Priority: `medium` · Check: `platform_manifests_reached` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_reliability/R-001` — Owner-managed application Deployments under \`k8s/applications/\` retain enough
  healthy capacity during rollout. Temporary capacity cost is acceptable when it
  prevents user-visible interruption.
  - Category: `reliability` · Priority: `high` · Check: `deployment_rollout_capacity` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_reliability/R-002` — Every HelmRelease a deployment profile applies sets a timeout and retries both
  a failed install and a failed upgrade, rolling an upgrade back rather than
  uninstalling it. A slow or failed chart upgrade recovers without an operator.
  
  Evidence: \[kube-prometheus-stack HelmRelease\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/infrastructure/observability/kube-prometheus-stack.yaml)
  
  Caveat: retries can mask a genuinely broken chart until they run out; the
  HelmRelease's Ready condition still reports the failure.
  - Category: `reliability` · Priority: `high` · Check: `helm_releases_self_heal` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_reliability/R-003` — Every application Deployment the platform delivers is the target of a Flagger
  Canary whose analysis checks metrics, fails after a threshold, and never shifts
  all traffic at once, so a bad release rolls back automatically.
  
  Evidence: \[shared Canary template\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/applications/platform/canary.yaml)
  - Category: `reliability` · Priority: `high` · Check: `delivered_apps_canary_with_rollback` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_reliability/R-004` — An application that uses the platform broker (its manifests set \`NATS\_URL\`)
  declares \`APP\_MESSAGING\_PREFIX\` in its \`fleet-app.yaml\` contract, and names its
  subjects, streams and buckets with that prefix, so applications sharing the
  broker cannot collide and every subject has a recorded owner.
  
  Evidence: \[messaging guide\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/docs/MESSAGING.md)
  
  Caveat: the check reads the declaration, not runtime subject names, and a
  prefix is not isolation (see S-015).
  - Category: `reliability` · Priority: `medium` · Check: `messaging_apps_declare_channels` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_reliability/R-005` — On the AWS staging profile every application keeps at least two replicas and
  a PodDisruptionBudget, so cluster-autoscaler scale-down and node upgrades never
  take an application fully offline. The extra replica's cost is accepted. The
  local single-node profile is exempt.
  
  Evidence: \[AWS staging profile\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/profiles/aws-staging)
  - Category: `reliability` · Priority: `medium` · Check: `aws_apps_survive_node_drains` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-001` — GitHub Actions uses short-lived OIDC credentials; long-lived AWS access keys are not allowed.
  
  Evidence: \[OIDC design\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/GITHUB-OIDC-SETUP.md)
  
  Caveat: the trust policy is generated from the adopter's \`OWNER/REPOSITORY\`,
  deployment branch, and GitHub Environment inputs. Repository analysis can verify
  that desired state and workflow credential method, but cannot attest which role
  version is live in AWS.
  - Category: `security` · Priority: `high` · Check: `github_actions_uses_oidc` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_security/S-002` — Application containers run as non-root users with privilege escalation disabled and all Linux capabilities dropped.
  
  Evidence: \[application Deployment\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/deployment.yaml)
  - Category: `security` · Priority: `high` · Check: `application_containers_hardened` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_security/S-003` — Application ingress is limited to the declared ingress, observability, Flux load
  tester, and same-workload peers.
  
  Evidence: \[NetworkPolicy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)
  - Category: `security` · Priority: `high` · Check: `application_ingress_restricted` · Reason: `complete_evidence_supports_intent`
- `satisfied` `infra_fleet_public_security/S-004` — Permissive application egress is accepted for the current staging environment.
  
  Evidence: \[current egress policy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/k8s/applications/load-harness/networkpolicy.yaml)
  - Category: `security` · Priority: `medium` · Check: `permissive_egress_bounded` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-005` — When an AWS staging deployment enables a public hostname, external application
  traffic uses HTTPS with certificates managed by cert-manager and Let's Encrypt.
  
  Evidence: \[TLS and optional DNS\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/TLS-SSL-SETUP.md)
  
  Caveat: the template defaults to a reserved \`.invalid\` hostname and port-forward
  access. New public exposure remains blocked by the documented ingress-controller
  migration, and repository desired state cannot prove a certificate is live.
  - Category: `security` · Priority: `high` · Check: `public_ingress_https` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_security/S-006` — A publicly reachable EKS API protected by IAM is accepted for staging only.
  
  Evidence: \[staging access decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/EKS-ACCESS.md)
  - Category: `security` · Priority: `high` · Check: `eks_public_endpoint_staging_only` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_security/S-007` — Service-wide IAM action wildcards such as \`eks:\*\` are not acceptable for a
  production or persistent environment.
  
  Evidence: \[current IAM disposition\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  
  Caveat: the persistent policy now enumerates actions and deliberately retains
  the read-only \`ec2:Describe\*\` prefix. Several IAM write actions still use
  \`Resource = "\*"\`; that residual risk and live AWS validation are outside the
  registered service-action-wildcard check.
  - Category: `security` · Priority: `critical` · Check: `persistent_iam_avoids_wildcards` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-008` — CSRF protection is not required for the current API-first staging application.
  
  Evidence: \[documented CSRF decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  
  Caveat: the application is not purely API-first — when \`API\_KEY\` is
  configured, Flask session-cookie authentication protects \`/ui/\*\` POST routes,
  including endpoints that start CPU, memory, and cluster load tests. This
  proposition holds only if \`SameSite=Lax\` is the accepted compensating
  control for those routes; otherwise CSRF exposure remains.
  - Category: `security` · Priority: `high` · Check: `session_cookie_csrf_compensated` · Reason: `collector_cannot_prove_satisfaction`
- `satisfied` `infra_fleet_public_security/S-009` — Automatic Kubernetes service-account token mounting is accepted for the current application.
  
  Evidence: \[documented token-mount decision\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/SECURITY-CONCERNS.md)
  - Category: `security` · Priority: `medium` · Check: `mounted_token_unprivileged` · Reason: `complete_evidence_supports_intent`
- `declared_unverified` `infra_fleet_public_security/S-010` — Repository owners enable dependency alerts and security-update pull requests;
  routine version checks run monthly, while review and deployment remain an owned
  operational decision.
  
  Evidence: \[Dependabot operating model\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/docs/DEPENDABOT.md)
  
  Caveat: this check reads the committed Dependabot configuration only; the
  repository-level alert and security-update settings it relies on are checked
  separately by S-012. This proposition defines no remediation SLA.
  - Category: `security` · Priority: `medium` · Check: `dependency_updates_configured` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_security/S-011` — Trivy blocks ECR publication when an image has any fixed Critical or High vulnerability; a documented exception is required to permit one.
  
  Evidence: \[Trivy publication gate\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d052789bd2e43b2c4be08d54e4ea1db6af4bd2b0/.github/workflows/load-harness-ci.yml)
  
  Caveat: the workflow sets \`ignore-unfixed: true\`, so unfixed Critical/High
  findings do not block, and the gate applies to ECR publication, not to
  deployment. The proposition text above has been narrowed to match; a \`Yes\`
  does not imply a deployment-time gate exists.
  - Category: `security` · Priority: `high` · Check: `ecr_publication_scan_gated` · Reason: `collector_cannot_prove_satisfaction`
- `declared_unverified` `infra_fleet_public_security/S-012` — Dependabot alerts and Dependabot security updates are enabled on the fleet
  repository, so a vulnerable pinned dependency raises an alert and a fix pull
  request without waiting for the monthly schedule.
  
  Evidence: \[Repository settings snapshot (PDR 0009)\](https&#58;//github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/decisions/0009-repository-settings-evidence.md)
  
  Caveat: the settings are read from the GitHub API just before each nightly
  review. Without a settings token, or for a pre-merge intent gate run, the
  position stays unverified rather than satisfied.
  - Category: `security` · Priority: `medium` · Check: `repository_security_updates_enabled` · Reason: `collector_incomplete`
- `declared_unverified` `infra_fleet_public_security/S-013` — Secret scanning and secret push protection are enabled on the fleet
  repository. It is public, so a committed credential must be blocked at push
  time and reported if one ever lands, never discovered by chance.
  
  Evidence: \[Repository settings snapshot (PDR 0009)\](https&#58;//github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/decisions/0009-repository-settings-evidence.md)
  
  Caveat: read from the settings snapshot taken before each nightly review;
  without it the position stays unverified, never satisfied.
  - Category: `security` · Priority: `high` · Check: `repository_secret_protection_enabled` · Reason: `collector_incomplete`
- `declared_unverified` `infra_fleet_public_security/S-014` — The fleet's default branch accepts changes only through pull requests and
  cannot be force-pushed or deleted, so every change on it has passed the merge
  gate's checks and its history cannot be rewritten.
  
  Evidence: \[Repository settings snapshot (PDR 0009)\](https&#58;//github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/decisions/0009-repository-settings-evidence.md)
  
  Caveat: protection settings are owner-only to change; a divergence is reported
  for the owner, never corrected by an agent.
  - Category: `security` · Priority: `high` · Check: `default_branch_protected` · Reason: `collector_incomplete`
- `declared_unverified` `infra_fleet_public_security/S-015` — The platform message broker accepts connections only from the \`applications\`
  namespace on the client port 4222 and from \`observability\` on the metrics port
  7777\. It runs without client authentication, so the network is its boundary.
  A new client namespace or port is a change to this position.
  
  Evidence: \[broker NetworkPolicy\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/47f88321414e2fef2616e886da7bb7bee2634ec3/k8s/infrastructure/messaging/networkpolicy.yaml)
  
  Caveat: the broker chart is not rendered, so its pods are assumed to carry
  Helm's standard \`app.kubernetes.io/name\` and \`app.kubernetes.io/instance\`
  labels; a policy can be shown open, never proven to select the real pods.
  Only a namespace-name label (\`matchLabels\` or an \`In\` expression) bounds a
  peer; \`Exists\` or \`NotIn\` selectors and port items without a single \`port\`
  count as open.
  - Category: `security` · Priority: `high` · Check: `message_broker_ingress_restricted` · Reason: `collector_cannot_prove_satisfaction`
- `divergent` `infra_fleet_public_security/S-016` — Every namespace that runs application Deployments enforces Pod Security
  \`restricted\` (\`pod-security.kubernetes.io/enforce: restricted\`), so admission
  rejects a privileged, root or host-namespace application pod even when its
  manifest regresses.
  
  Evidence: \[applications namespace\](https&#58;//github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/infrastructure/namespaces/applications.yaml)
  
  Caveat: the label is desired state; whether every canary and load-test pod
  admits under it is proven on a live cluster, not here.
  - Category: `security` · Priority: `high` · Check: `app_namespaces_enforce_restricted` · Reason: `evidence_conflicts_with_intent`
  - Evidence: `platform_collector:ae9c78eb6384533a`

## Recommendations

### #1 [unchanged] An application namespace does not enforce Pod Security restricted

- Category: `security` · Priority: `high` · Confidence: 0.95
- Fingerprint: `fp_51422acc6541b061859ad9a1`
- Evidence: `platform_collector:ae9c78eb6384533a`

A namespace that runs application Deployments lacks pod-security.kubernetes.io/enforce: restricted.

**Impact:** A new or changed application can run privileged, root or host-namespace pods; nothing at admission stops the regression.

**Suggested change:** Label the application namespace with pod-security.kubernetes.io/enforce: restricted, after checking canary and load-test pods meet it.

**Trade-offs:** Any pod in the namespace that needs more privilege must move elsewhere.

### [resolved] Public ingress can serve application traffic over plain HTTP

- Category: `security` · Priority: `high` · Confidence: 0.85
- Fingerprint: `fp_dcc368602d7a63507c7f95c3`
- Evidence: `kubernetes_security_collector:69d40db0b198099c`, `kubernetes_security_collector:6f5caf53a3bf6294`

An Ingress does not cover every host with TLS from a cert-manager issuer, or it disables the HTTP-to-HTTPS redirect.

**Impact:** Once a real hostname is configured, credentials and session cookies can cross the internet unencrypted.

**Suggested change:** Cover every host with a cert-manager TLS entry and keep the HTTPS redirect on; route in-cluster analysis traffic to the service or an internal listener instead.

**Trade-offs:** Canary analysis that currently measures HTTP through the public ingress needs an internal path, or it measures redirects instead of the canary.

### [resolved] EKS worker group cannot scale on demand

- Category: `cost` · Priority: `high` · Confidence: 0.85
- Fingerprint: `fp_7ec808b779a06a62a8f1b78f`
- Evidence: `terraform_cost_collector:d31a3916e8b5bd2a`

A staging managed node group declares size bounds, but nothing in the repository drives them: no cluster-autoscaler, Karpenter or EKS Auto Mode is declared, or the maximum is not explicit and above the minimum.

**Impact:** Capacity stays at the desired size regardless of load: pods scaled out by the HPA can stay pending, and idle capacity is never released.

**Suggested change:** Declare a node autoscaler for the staging cluster (cluster-autoscaler with a pod identity role, Karpenter, or EKS Auto Mode), keep an explicit bounded max_size, and lower min_size to zero unless a named workload needs an always-on node.

**Trade-offs:** An autoscaler adds a controller, IAM permissions and scale-up latency; a zero minimum delays the first workload after idle periods.

### [resolved] Staging capacity is never released on a schedule

- Category: `cost` · Priority: `high` · Confidence: 0.80
- Fingerprint: `fp_156438b3cb31a7781fe4fc70`
- Evidence: `terraform_cost_collector:831d0b3bb6653a0a`

Staging worker capacity has no scheduled scale-to-zero: no aws_autoscaling_schedule reaching zero and no scheduled workflow that tears the stack down.

**Impact:** Idle staging compute is billed around the clock unless someone remembers to stop it.

**Suggested change:** Schedule the release: an aws_autoscaling_schedule to zero outside the usage window, or a cron trigger on the teardown workflow with an owner-set window.

**Trade-offs:** Starting after the window costs the declared up-to-30-minute delay; a scheduled teardown also needs an unattended confirmation path.

### [resolved] Public ingress can serve application traffic over plain HTTP

- Category: `security` · Priority: `high` · Confidence: 0.85
- Fingerprint: `fp_90d0fb2169abf0b8849a8d79`
- Evidence: `kubernetes_security_collector:6f5caf53a3bf6294`

An Ingress does not cover every host with TLS from a cert-manager issuer, or it disables the HTTP-to-HTTPS redirect.

**Impact:** Once a real hostname is configured, credentials and session cookies can cross the internet unencrypted.

**Suggested change:** Cover every host with a cert-manager TLS entry and keep the HTTPS redirect on; route in-cluster analysis traffic to the service or an internal listener instead.

**Trade-offs:** Canary analysis that currently measures HTTP through the public ingress needs an internal path, or it measures redirects instead of the canary.

### [resolved] Tracked dependency manifests lack monthly Dependabot updates

- Category: `security` · Priority: `medium` · Confidence: 0.90
- Fingerprint: `fp_32aef5c30310be194e284fe4`
- Evidence: `dependency_update_collector:c75dced6323eba06`, `dependency_update_collector:393b67d709c744d8`

A tracked manifest directory (a Dockerfile, Python requirements, pinned Terraform, workflows) has no matching Dependabot entry, or its entry is not scheduled monthly.

**Impact:** Pinned versions and image digests in that directory never receive routine or security update pull requests and silently age.

**Suggested change:** Add a monthly Dependabot entry for that ecosystem and directory, grouped like the existing entries, or remove the unused manifest.

**Trade-offs:** More dependency pull requests to review each month.

### [resolved] Terraform resources lack cost-allocation tags

- Category: `cost` · Priority: `medium` · Confidence: 0.90
- Fingerprint: `fp_b342e48d905647ef74ddc267`
- Evidence: `terraform_cost_collector:444d9162e4a0b4b7`, `terraform_cost_collector:716686c2cfdaac9d`

Resources in a root module set tags that lack an environment, service or owner key, and the AWS provider's default_tags do not supply the missing keys.

**Impact:** Billed usage of the listed resources, and of any other resource that does not tag itself, may go unattributed when the bill is split by environment, service or owner.

**Suggested change:** Add default_tags { tags = { Environment, Service, Owner } } to every aws provider, for example from a shared local, and activate the keys as cost-allocation tags.

**Trade-offs:** Changing default tags updates every taggable resource on the next apply; some resources, such as instances launched by node groups, still need tag propagation.

### [resolved] AWS staging lifecycle lacks a declared onboarding or teardown control

- Category: `maintainability` · Priority: `high` · Confidence: 0.90
- Fingerprint: `fp_1b74b45b8223503fca7d7a49`
- Evidence: `fleet_lifecycle_collector:9fe9dbe2d300812e`

The aws-staging strategy or its onboarding coordinator does not show every static control: plan-by-default setup, reported targets, stdin-only secrets, a next command, and a teardown confirmation typed by the operator.

**Impact:** An adopter can mutate or destroy a billable AWS target without first seeing and confirming it, or leak a credential through process arguments.

**Suggested change:** Keep setup in plan mode unless --apply is given, print the AWS and GitHub targets before mutation, pipe secrets to gh secret set, print the next lifecycle command, and have down show its target and pass the operator's typed confirmation to the teardown workflow instead of a hard-coded one.

**Trade-offs:** Interactive confirmation makes unattended teardown require an explicit, separately supplied confirmation value.

### [resolved] Staging CloudWatch log group keeps logs longer than 30 days

- Category: `cost` · Priority: `medium` · Confidence: 0.90
- Fingerprint: `fp_71b389eab950ffc8b4efa99c`
- Evidence: `terraform_cost_collector:d2d6fa1dfde83257`

A staging log group declared directly or created by a pinned module retains events for more than 30 days or never expires them.

**Impact:** Log storage grows with every rebuild cycle and is billed after the staging environment's usefulness for debugging has passed.

**Suggested change:** Declare an explicit retention of at most 30 days, for the EKS module via cloudwatch_log_group_retention_in_days, or document why longer retention is needed.

**Trade-offs:** Shorter retention removes older control-plane audit trails that could help a late incident investigation.

### [resolved] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_6a206c70c062521f8d4d2145`
- Evidence: `terraform_iam_collector:00dfe82f2366c9e7`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.

### [resolved] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_b3cb0f1396ed1d3f4d4518b4`
- Evidence: `terraform_iam_collector:f9516f33c203f5c8`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.
