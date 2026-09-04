# Test security intent

- Format: `1`
- Intent ID: `test_security_intent`
- Version: `1.0`
- Category: `security`

This preamble is explanatory and is not a proposition.

## S-001 · CI credentials

### Intent

GitHub Actions uses OIDC-only AWS credentials.

### Evaluation

- Check: `github_actions_uses_oidc`
- Priority: `high`

## S-007 · Persistent IAM

### Intent

Persistent IAM policies avoid wildcard grants.

### Evaluation

- Check: `persistent_iam_avoids_wildcards`
- Priority: `critical`

## T-001 · Image scanning

### Intent

Trivy does not ignore unfixed Critical or High vulnerabilities.

### Evaluation

- Check: `trivy_does_not_ignore_unfixed`
- Priority: `medium`
