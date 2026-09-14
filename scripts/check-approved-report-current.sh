#!/usr/bin/env bash
set -euo pipefail

# Run inside the trusted advisor checkout. Fetching main is a public read;
# the report and inputs are compared as data, and no fetched code is executed.
approved_report="${1:?approved report path is required}"
git fetch --quiet --no-tags origin main
git show FETCH_HEAD:reports/report.json > "$RUNNER_TEMP/latest-report.json"

if ! cmp -s "$approved_report" "$RUNNER_TEMP/latest-report.json" ||
   ! git diff --quiet HEAD FETCH_HEAD -- \
      policy.yaml intent src pyproject.toml uv.lock \
      .github/workflows/fleet-issues.yml scripts/check-approved-report-current.sh; then
  echo false
  exit 0
fi
echo true
