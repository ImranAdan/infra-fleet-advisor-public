# Initial cost intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_cost`
- Version: `1.5`
- Category: `cost`

This document declares the fleet owner's initial AWS cost position. It does not
claim that the current repository already satisfies any proposition. Reliability
or recovery-time trade-offs must remain visible when cost reductions are
recommended.

## C-001 · Idle staging capacity

### Intent

Staging application worker capacity scales to zero outside an owner-defined
usage window. A delayed startup of up to 30 minutes is acceptable when it avoids
paying for otherwise idle compute.

### Evaluation

- Check: `staging_capacity_released_on_schedule`
- Priority: `high`

## C-002 · Worker scaling bounds

### Intent

Every non-production EKS worker group declares demand-driven scaling with a zero
minimum where its workloads permit it and an explicit bounded maximum. Any
always-on baseline must name the workload that requires it.

### Evaluation

- Check: `worker_groups_demand_scaled`
- Priority: `high`

## C-003 · Log retention

### Intent

Every staging CloudWatch log group managed by the fleet has an explicit
retention period of no more than 30 days. Longer retention requires a documented
operational or compliance reason.

### Evaluation

- Check: `staging_log_retention_bounded`
- Priority: `medium`

## C-004 · Container image lifecycle

### Intent

Every ECR repository managed by the fleet has a lifecycle policy that removes
untagged images and bounds the number or age of retained images. Images retained
for rollback or audit have an explicit exception.

### Evaluation

- Check: `ecr_lifecycle_bounded`
- Priority: `medium`

## C-005 · Cost allocation tags

### Intent

Terraform-managed AWS resources that support tagging declare consistent
environment, service, and owner tags so billed usage can be attributed. Any
resource that cannot carry these tags is reported as an explicit coverage gap.

### Evaluation

- Check: `aws_cost_allocation_tags`
- Priority: `medium`

## C-006 · Local footprint budget

### Intent

The local profile fits a laptop: the CPU and memory requests it declares in Git,
summed over workloads and HelmRelease values, stay within 1 CPU and 2 GiB. A
component that needs more is a deliberate change to this budget.

Evidence: [local profile](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/clusters/local)

Caveat: chart defaults are not rendered, so the declared sum is a lower bound
and the check can show the budget exceeded, never met.

### Evaluation

- Check: `local_footprint_within_budget`
- Priority: `medium`

## C-007 · Bounded metrics retention

### Intent

Prometheus keeps metrics for a bounded time and size, so telemetry never grows
until it fills a node's disk.

Evidence: [kube-prometheus-stack values](https://github.com/ImranAdan/infra-fleet-public/blob/d973708aba130e5f23bbf0146c52dfec1185a820/k8s/infrastructure/observability/kube-prometheus-stack.yaml)

### Evaluation

- Check: `metrics_retention_bounded`
- Priority: `medium`
