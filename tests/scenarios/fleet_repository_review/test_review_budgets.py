import pytest

from infra_fleet_advisor.core.errors import BoundedExecutionExceeded
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.review import (
    check_model_call_budget,
    check_wall_clock_budget,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=10,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=1024,
    max_recommendations=10,
)


def test_wall_clock_within_budget_is_fine() -> None:
    check_wall_clock_budget(5.0, LIMITS)


def test_wall_clock_over_budget_raises() -> None:
    with pytest.raises(BoundedExecutionExceeded):
        check_wall_clock_budget(11.0, LIMITS)


def test_model_calls_within_budget_is_fine() -> None:
    check_model_call_budget(1, LIMITS)


def test_model_calls_over_budget_raises() -> None:
    with pytest.raises(BoundedExecutionExceeded):
        check_model_call_budget(2, LIMITS)
