# Initial reliability intent for `infra-fleet-public`

- Format: `1`
- Intent ID: `infra_fleet_public_reliability`
- Version: `1.0`
- Category: `reliability`

This document declares the fleet owner's initial reliability position. It does
not claim that the current repository already satisfies the proposition.

## R-001 · Rollout capacity

### Intent

Deployments retain enough healthy capacity during rollout. Temporary capacity
cost is acceptable when it prevents user-visible interruption.

### Evaluation

- Check: `deployment_rollout_capacity`
- Priority: `high`
