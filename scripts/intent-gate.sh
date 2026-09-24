#!/usr/bin/env bash
# Review a fleet change's base and head with this advisor and fail when the
# head newly diverges from declared intent. Read-only: the fleet checkout is
# only used to create two detached worktrees, which are removed afterwards.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "Usage: $0 FLEET_CHECKOUT BASE_SHA HEAD_SHA OUTPUT_DIR" >&2
  exit 2
fi
fleet=$(cd "$1" && pwd)
base_sha=$2
head_sha=$3
output=$4
advisor_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

for sha in "$base_sha" "$head_sha"; do
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Commits must be full lowercase SHAs." >&2
    exit 2
  fi
done

mkdir -p "$output"
worktrees=$(mktemp -d)
cleanup() {
  git -C "$fleet" worktree remove --force "$worktrees/base" >/dev/null 2>&1 || true
  git -C "$fleet" worktree remove --force "$worktrees/head" >/dev/null 2>&1 || true
  rm -rf "$worktrees"
}
trap cleanup EXIT

review() {
  local name=$1 sha=$2
  git -C "$fleet" worktree add --quiet --detach "$worktrees/$name" "$sha"
  uv run --frozen --project "$advisor_root" infra-fleet-advisor review \
    --checkout "$worktrees/$name" --sha "$sha" \
    --policy "$advisor_root/policy.yaml" --intent-dir "$advisor_root/intent" \
    --output-dir "$output/$name" --synthesizer stub >/dev/null
}

review base "$base_sha"
review head "$head_sha"
uv run --frozen --project "$advisor_root" infra-fleet-advisor gate \
  --base-report "$output/base/report.json" \
  --head-report "$output/head/report.json" \
  ${GITHUB_STEP_SUMMARY:+--summary "$GITHUB_STEP_SUMMARY"}
