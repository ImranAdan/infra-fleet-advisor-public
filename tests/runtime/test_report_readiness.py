import json
from pathlib import Path

import pytest

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.report_readiness import ReportReadiness, check_report_readiness
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY

FIXTURES = Path(__file__).parent.parent / "fixtures"
POLICY = FIXTURES / "policies" / "valid_policy.yaml"
INTENTS = FIXTURES / "intents"


def _report(path: Path, **overrides: str) -> Path:
    provenance = {
        "source_commit_sha": "a" * 40,
        "source_label": "infra-fleet-public",
        "policy_version": "1.0",
        "intent_digest": load_intent_catalog(INTENTS, TAXONOMY).digest,
        **overrides,
    }
    path.write_text(json.dumps({"provenance": provenance}))
    return path


def test_missing_report_waits_without_creating_a_baseline(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    assert check_report_readiness(path, POLICY, INTENTS) == ReportReadiness(False, "report_missing")
    assert not path.exists()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ReportReadiness(True, "current")),
        ({"policy_version": "previous"}, ReportReadiness(False, "policy_changed")),
        ({"intent_digest": "previous"}, ReportReadiness(False, "intent_changed")),
    ],
)
def test_readiness_compares_ratified_versions(
    tmp_path: Path, overrides: dict[str, str], expected: ReportReadiness
) -> None:
    path = _report(tmp_path / "report.json", **overrides)
    before = path.read_bytes()
    assert check_report_readiness(path, POLICY, INTENTS) == expected
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "overrides", [{"source_commit_sha": "abc123"}, {"source_label": "another-fleet"}]
)
def test_invalid_identity_fails_instead_of_waiting(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    path = _report(tmp_path / "report.json", **overrides)
    with pytest.raises(PolicyError):
        check_report_readiness(path, POLICY, INTENTS)


def test_malformed_report_fails_without_disclosing_input(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("untrusted report text")
    with pytest.raises(PolicyError, match="cannot read report provenance") as error:
        check_report_readiness(path, POLICY, INTENTS)
    assert str(path) not in str(error.value)
    assert "untrusted report text" not in str(error.value)
