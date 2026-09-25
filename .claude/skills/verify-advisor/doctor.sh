#!/usr/bin/env bash
# Read-only: is this advisor checkout and its fleet checkout fit to drive?
# Prints ok / warn / FAIL per check and exits 1 on any FAIL.
# Usage: doctor.sh [FLEET_CHECKOUT]   (default ../infra-fleet-public)
set -uo pipefail

root=$(git rev-parse --show-toplevel)
fleet=${1:-$root/../infra-fleet-public}
failed=0
ok() { printf 'ok    %s\n' "$*"; }
warn() { printf 'warn  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; failed=1; }

if ! command -v uv >/dev/null; then bad 'uv is not installed'; exit 1; fi
ok "uv $(uv --version | cut -d' ' -f2)"
if (cd "$root" && uv sync --frozen --quiet); then ok 'locked environment in sync (uv sync --frozen)'
else bad 'uv sync --frozen failed: the lockfile and pyproject disagree'; fi
if (cd "$root" && uv run --frozen infra-fleet-advisor --help >/dev/null 2>&1); then ok 'CLI starts'
else bad 'infra-fleet-advisor --help fails'; fi

if catalog=$(cd "$root" && uv run --frozen python - <<'PY' 2>&1
from pathlib import Path
from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import INTENT_CHECKS
catalog = load_intent_catalog(Path("intent"), TAXONOMY)
checked = [p for p in catalog.propositions if p.check_key in INTENT_CHECKS]
print(f"{len(catalog.propositions)} positions, {len(checked)} with a registered check")
PY
)
then ok "intent catalog loads: $catalog"; else bad "intent catalog does not load: ${catalog##*$'\n'}"; fi

if [ ! -d "$fleet/.git" ] && [ ! -f "$fleet/.git" ]; then
  bad "no fleet checkout at $fleet (pass its path as the first argument)"
else
  fleet=$(cd "$fleet" && pwd)
  if [ -n "$(git -C "$fleet" status --porcelain)" ]; then
    bad "fleet checkout $fleet is dirty; the advisor reviews clean commits only"
  else
    ok "fleet checkout clean at $(git -C "$fleet" rev-parse --short=12 HEAD) ($(git -C "$fleet" branch --show-current || echo detached))"
  fi
  behind=$(git -C "$fleet" rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
  [ "$behind" = 0 ] || warn "fleet HEAD is $behind commit(s) behind its last-fetched origin/main"
fi

exit "$failed"
