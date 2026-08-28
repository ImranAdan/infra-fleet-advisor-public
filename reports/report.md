# Infra Fleet Advisor report

- Source: `infra-fleet-public` @ `65857138c50f3ab24bb8f58834c8ca3afe84a929`
- Advisor version: `0.1.0` · Policy version: `1.0`
- Model: `stub-synthesizer-v1` · Run started: `2026-08-28T15:15:00.087266+00:00`
- Lifecycle: 2 new, 0 unchanged, 0 resolved, 0 suppressed (0 rejected)

## Collector coverage

- `github_actions_workflow_collector`: ok (13 evidence)
- `terraform_iam_collector`: ok (1 evidence)

## Recommendations

### #1 [new] IAM policy grants a wildcard action on all resources

- Category: `security` · Priority: `critical` · Confidence: 0.85
- Fingerprint: `fp_b3cb0f1396ed1d3f4d4518b4`
- Evidence: `terraform_iam_collector:f9516f33c203f5c8`

A Terraform-managed IAM policy statement allows a wildcard action (e.g. service:*) with Resource set to *.

**Impact:** Overly broad IAM grants expand the blast radius if the associated role's credentials are compromised, and make least-privilege review difficult.

**Suggested change:** Scope the action list to the specific API calls required, and constrain Resource to the specific ARNs the role needs instead of *.

**Trade-offs:** Narrowing permissions may require iterating as new resource types are added, and risks under-provisioning if scoped too tightly.

### #2 [new] Trivy CI gate ignores unfixed vulnerabilities

- Category: `security` · Priority: `medium` · Confidence: 0.85
- Fingerprint: `fp_6ecd2ba8ad2dbff1cc74a92a`
- Evidence: `github_actions_workflow_collector:2513baff5eb4d7c0`

The Trivy scan step sets ignore-unfixed, so Critical/High findings without an available fix do not block the pipeline.

**Impact:** Unpatchable-but-known vulnerabilities can reach a published image undetected.

**Suggested change:** Remove ignore-unfixed, or pair it with a documented, time-boxed exception process.

**Trade-offs:** May block builds on vulnerabilities with no vendor fix yet available.
