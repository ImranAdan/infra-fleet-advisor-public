import json
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.report import CollectorCoverage, Report, RunProvenance
from infra_fleet_advisor.runtime.report_writer import (
    load_prior_report,
    to_json,
    to_markdown,
    write_report,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"

REPORT = Report(
    provenance=RunProvenance(
        source_commit_sha="abc123",
        source_label="infra-fleet-public",
        advisor_version="0.1.0",
        policy_version="1.0",
        collector_versions={"c": "1.0.0"},
        model_identifier="stub-synthesizer-v1",
        run_started_at="2026-08-26T00:00:00+00:00",
    ),
    coverage=(CollectorCoverage("c", "ok", 1, None),),
    recommendations=(),
    rejected_count=0,
    new_count=0,
    unchanged_count=0,
    resolved_count=0,
    suppressed_count=0,
)


def test_json_and_markdown_derive_from_the_same_report() -> None:
    payload = json.loads(to_json(REPORT))
    markdown = to_markdown(REPORT)
    assert payload["provenance"]["source_commit_sha"] == REPORT.provenance.source_commit_sha
    assert REPORT.provenance.source_commit_sha in markdown


def test_report_never_contains_local_machine_paths() -> None:
    payload = to_json(REPORT)
    assert "/Users/" not in payload
    assert "checkout_path" not in payload


def test_write_report_creates_both_files(tmp_path: Path) -> None:
    json_path, md_path = write_report(REPORT, tmp_path / "out")
    assert json_path.exists()
    assert md_path.exists()


def test_load_prior_report_parses_sample_fixture() -> None:
    prior = load_prior_report(FIXTURES / "prior_reports" / "prior_report_sample.json")
    assert prior is not None
    assert prior.recommendations[0].concern_key == "static_aws_credentials_in_ci"


def test_load_prior_report_none_when_no_path() -> None:
    assert load_prior_report(None) is None


def test_load_prior_report_missing_file_raises_policy_error_not_crash(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_prior_report(tmp_path / "does-not-exist.json")


def test_load_prior_report_rejects_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"recommendations": [{"fingerprint": "x"}]}', encoding="utf-8")
    with pytest.raises(PolicyError):
        load_prior_report(bad)
