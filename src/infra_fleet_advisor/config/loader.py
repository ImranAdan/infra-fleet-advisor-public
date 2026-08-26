from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.config.policy import AcceptedTradeOff, AdvisorPolicy
from infra_fleet_advisor.core.errors import PolicyError, UnsafePathError
from infra_fleet_advisor.core.paths import validate_repo_relative_path

MAX_POLICY_FILE_BYTES = 64 * 1024
MAX_RECOMMENDATIONS_BOUNDS = (1, 50)
MAX_WALL_SECONDS_BOUNDS = (1, 3600)
MAX_MODEL_CALLS_BOUNDS = (1, 20)

_REQUIRED_KEYS = {
    "version",
    "max_recommendations",
    "max_wall_seconds",
    "max_model_calls",
    "enabled_categories",
    "category_priority",
    "accepted_trade_offs",
    "suppressed_concerns",
    "evidence_path_exclusions",
}


def _require_int_in(value: Any, bounds: tuple[int, int], field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PolicyError(f"{field_name} must be an integer")
    if not (bounds[0] <= value <= bounds[1]):
        raise PolicyError(f"{field_name} must be in [{bounds[0]}, {bounds[1]}]")
    return value


def load_policy(path: Path, allowed_categories: frozenset[str]) -> AdvisorPolicy:
    if path.stat().st_size > MAX_POLICY_FILE_BYTES:
        raise PolicyError(f"policy file exceeds {MAX_POLICY_FILE_BYTES} bytes")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PolicyError("policy must be a YAML mapping")

    unknown = set(raw) - _REQUIRED_KEYS
    if unknown:
        raise PolicyError(f"unknown policy fields: {sorted(unknown)}")
    missing = _REQUIRED_KEYS - set(raw)
    if missing:
        raise PolicyError(f"missing policy fields: {sorted(missing)}")

    enabled_categories = frozenset(raw["enabled_categories"])
    if not enabled_categories or not enabled_categories.issubset(allowed_categories):
        raise PolicyError(f"enabled_categories must be a non-empty subset of {allowed_categories}")

    category_priority = raw["category_priority"]
    if not isinstance(category_priority, dict) or not set(category_priority).issubset(
        allowed_categories
    ):
        raise PolicyError("category_priority keys must be known categories")

    trade_offs = [
        AcceptedTradeOff(concern_key=t["concern_key"], rationale=t["rationale"])
        for t in raw["accepted_trade_offs"]
    ]

    try:
        exclusions = [validate_repo_relative_path(p) for p in raw["evidence_path_exclusions"]]
    except UnsafePathError as exc:
        raise PolicyError(f"unsafe evidence_path_exclusions entry: {exc}") from exc

    return AdvisorPolicy(
        version=str(raw["version"]),
        max_recommendations=_require_int_in(
            raw["max_recommendations"], MAX_RECOMMENDATIONS_BOUNDS, "max_recommendations"
        ),
        max_wall_seconds=_require_int_in(
            raw["max_wall_seconds"], MAX_WALL_SECONDS_BOUNDS, "max_wall_seconds"
        ),
        max_model_calls=_require_int_in(
            raw["max_model_calls"], MAX_MODEL_CALLS_BOUNDS, "max_model_calls"
        ),
        enabled_categories=enabled_categories,
        category_priority=category_priority,
        accepted_trade_offs=trade_offs,
        suppressed_concerns=frozenset(raw["suppressed_concerns"]),
        evidence_path_exclusions=exclusions,
    )
