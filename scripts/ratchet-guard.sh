#!/usr/bin/env bash
# Review one fleet commit with the base advisor and with this checkout, then
# fail when this checkout loses proof, a check, or a finding. The fleet is held
# constant, so every difference is the advisor's doing. Read-only: the fleet is
# only used to create a detached worktree, which is removed afterwards.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 FLEET_CHECKOUT BASE_ADVISOR_SHA OUTPUT_DIR" >&2
  exit 2
fi
fleet=$(cd "$1" && pwd)
base_sha=$2
output=$3
advisor_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ! "$base_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BASE_ADVISOR_SHA must be a full lowercase SHA." >&2
  exit 2
fi
case "$output" in /*) ;; *) output="$PWD/$output" ;; esac
case "$output/" in
  "$fleet"/*|"$advisor_root"/*)
    echo "OUTPUT_DIR must be outside both checkouts." >&2
    exit 2 ;;
esac
mkdir -p "$output"

work=$(mktemp -d)
cleanup() {
  git -C "$advisor_root" worktree remove --force "$work/advisor" >/dev/null 2>&1 || true
  git -C "$fleet" worktree remove --force "$work/fleet" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

fleet_sha=$(git -C "$fleet" rev-parse HEAD)
git -C "$fleet" worktree add --quiet --detach "$work/fleet" "$fleet_sha"
git -C "$advisor_root" worktree add --quiet --detach "$work/advisor" "$base_sha"

review() {
  local root=$1 out=$2
  uv run --frozen --project "$root" infra-fleet-advisor review \
    --checkout "$work/fleet" --sha "$fleet_sha" \
    --policy "$root/policy.yaml" --intent-dir "$root/intent" \
    --output-dir "$out" --synthesizer stub >/dev/null
}

review "$work/advisor" "$output/base"
review "$advisor_root" "$output/head"
uv run --frozen --project "$advisor_root" infra-fleet-advisor ratchet \
  --base-report "$output/base/report.json" \
  --head-report "$output/head/report.json" \
  ${GITHUB_STEP_SUMMARY:+--summary "$GITHUB_STEP_SUMMARY"}
