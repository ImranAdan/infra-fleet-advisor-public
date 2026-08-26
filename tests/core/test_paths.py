import pytest

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.paths import validate_repo_relative_path


@pytest.mark.parametrize(
    "raw",
    ["", "  ", "/etc/passwd", "../secrets.yaml", "a/../../b", "C:/Windows", ".."],
)
def test_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(UnsafePathError):
        validate_repo_relative_path(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(".github/workflows/ci.yml", ".github/workflows/ci.yml"), ("a/./b", "a/b")],
)
def test_normalizes_safe_paths(raw: str, expected: str) -> None:
    assert validate_repo_relative_path(raw) == expected
