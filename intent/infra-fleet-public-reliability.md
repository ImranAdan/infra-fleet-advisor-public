# Initial reliability intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_reliability`
- Version: `1.2`
- Category: `reliability`

This document declares the fleet owner's initial reliability position. It does
not claim that the current repository already satisfies the proposition.

## R-001 · Rollout capacity

### Intent

Owner-managed application Deployments under `k8s/applications/` retain enough
healthy capacity during rollout. Temporary capacity cost is acceptable when it
prevents user-visible interruption.

### Evaluation

- Check: `deployment_rollout_capacity`
- Priority: `high`

## R-002 · Platform releases recover by themselves

### Intent

Every HelmRelease a deployment profile applies sets a timeout and retries both
a failed install and a failed upgrade, rolling an upgrade back rather than
uninstalling it. A slow or failed chart upgrade recovers without an operator.

Evidence: [kube-prometheus-stack HelmRelease](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/infrastructure/observability/kube-prometheus-stack.yaml)

Caveat: retries can mask a genuinely broken chart until they run out; the
HelmRelease's Ready condition still reports the failure.

### Evaluation

- Check: `helm_releases_self_heal`
- Priority: `high`

## R-003 · Canary delivery with rollback

### Intent

Every application Deployment the platform delivers is the target of a Flagger
Canary whose analysis checks metrics, fails after a threshold, and never shifts
all traffic at once, so a bad release rolls back automatically.

Evidence: [shared Canary template](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/applications/platform/canary.yaml)

### Evaluation

- Check: `delivered_apps_canary_with_rollback`
- Priority: `high`

## R-004 · Messaging contract

### Intent

An application that uses the platform broker (its manifests set `NATS_URL`)
declares `APP_MESSAGING_PREFIX` in its `fleet-app.yaml` contract, and names its
subjects, streams and buckets with that prefix, so applications sharing the
broker cannot collide and every subject has a recorded owner.

Evidence: [messaging guide](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/docs/MESSAGING.md)

Caveat: the check reads the declaration, not runtime subject names, and a
prefix is not isolation (see S-015).

### Evaluation

- Check: `messaging_apps_declare_channels`
- Priority: `medium`

## R-005 · AWS staging survives node drains

### Intent

On the AWS staging profile every application keeps at least two replicas and
a PodDisruptionBudget, so cluster-autoscaler scale-down and node upgrades never
take an application fully offline. The extra replica's cost is accepted. The
local single-node profile is exempt.

Evidence: [AWS staging profile](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/profiles/aws-staging)

### Evaluation

- Check: `aws_apps_survive_node_drains`
- Priority: `medium`
