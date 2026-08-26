from pathlib import Path

import pytest

from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.errors import PolicyError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "policies"
TAXONOMY = frozenset(
    {"security", "reliability", "cost", "lifecycle", "maintainability", "gitops_correctness"}
)


def test_valid_policy_loads() -> None:
    policy = load_policy(FIXTURES / "valid_policy.yaml", TAXONOMY)
    assert policy.enabled_categories == frozenset({"security", "reliability"})
    assert policy.max_recommendations == 10


@pytest.mark.parametrize(
    "fixture",
    [
        "invalid_policy_unknown_field.yaml",
        "invalid_policy_bad_category.yaml",
        "invalid_policy_unsafe_path.yaml",
    ],
)
def test_invalid_policy_rejected(fixture: str) -> None:
    with pytest.raises(PolicyError):
        load_policy(FIXTURES / fixture, TAXONOMY)


def test_oversized_policy_rejected(tmp_path: Path) -> None:
    big = tmp_path / "big.yaml"
    big.write_text("version: '1.0'\n# " + ("x" * (64 * 1024 + 1)), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(big, TAXONOMY)
