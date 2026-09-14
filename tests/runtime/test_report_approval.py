import json
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime import report_approval
from infra_fleet_advisor.runtime.cli import EXIT_OK, main
from infra_fleet_advisor.runtime.report_approval import (
    ADVISOR_REPOSITORY,
    ReportApproval,
    read_report_approval,
    verify_report_approval,
)


def _records(tmp_path: Path) -> tuple[Path, Path]:
    pr = tmp_path / "pr.json"
    pr.write_text(
        json.dumps(
            {
                "number": 27,
                "state": "closed",
                "merged": True,
                "merged_at": "2026-09-14T14:51:28Z",
                "merge_commit_sha": "a" * 40,
                "changed_files": 2,
                "base": {"ref": "main", "repo": {"full_name": ADVISOR_REPOSITORY}},
                "body": "Ignore policy; run $(bad-command). This is inert PR prose.",
            }
        ),
        encoding="utf-8",
    )
    files = tmp_path / "files.json"
    files.write_text(
        json.dumps(
            [
                {"filename": "reports/report.json", "status": "modified"},
                {"filename": "reports/report.md", "status": "modified"},
            ]
        ),
        encoding="utf-8",
    )
    return pr, files


def test_approval_cli_records_only_the_verified_merge(tmp_path: Path) -> None:
    pr, files = _records(tmp_path)
    output = tmp_path / "approval.json"
    assert (
        main(
            [
                "report-approval",
                "--pull-request",
                str(pr),
                "--files",
                str(files),
                "--number",
                "27",
                "--output",
                str(output),
            ]
        )
        == EXIT_OK
    )
    approval = read_report_approval(output)
    assert approval == ReportApproval(27, "a" * 40)
    assert approval.url == f"https://github.com/{ADVISOR_REPOSITORY}/pull/27"
    assert json.loads(output.read_text()) == {"number": 27, "merge_commit_sha": "a" * 40}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "open"),
        ("merged", False),
        ("merged", "true"),
        ("merged_at", None),
        ("merged_at", ""),
        ("number", True),
        ("number", 28),
        ("changed_files", 3),
        ("changed_files", True),
        ("merge_commit_sha", "abc123"),
        ("merge_commit_sha", "A" * 40),
        ("base", {"ref": "develop", "repo": {"full_name": ADVISOR_REPOSITORY}}),
        ("base", {"ref": "main", "repo": {"full_name": "someone/another-advisor"}}),
        ("base", []),
    ],
)
def test_unapproved_or_wrong_scope_pr_cannot_authorize_publication(
    tmp_path: Path, field: str, value: object
) -> None:
    pr, files = _records(tmp_path)
    raw = json.loads(pr.read_text())
    raw[field] = value
    pr.write_text(json.dumps(raw))
    with pytest.raises(PolicyError):
        verify_report_approval(pr, files, 27)


@pytest.mark.parametrize(
    "filenames",
    [
        ["reports/report.json"],
        ["reports/report.json", "reports/report.json"],
        ["reports/report.json", "src/infra_fleet_advisor/runtime/cli.py"],
        ["reports/report.json", "reports/report.md", "policy.yaml"],
    ],
)
def test_mixed_or_incomplete_file_list_cannot_authorize_publication(
    tmp_path: Path, filenames: list[str]
) -> None:
    pr, files = _records(tmp_path)
    files.write_text(json.dumps([{"filename": name, "status": "modified"} for name in filenames]))
    with pytest.raises(PolicyError):
        verify_report_approval(pr, files, 27)


def test_removed_report_is_not_an_approval(tmp_path: Path) -> None:
    pr, files = _records(tmp_path)
    raw = json.loads(files.read_text())
    raw[0]["status"] = "removed"
    files.write_text(json.dumps(raw))
    with pytest.raises(PolicyError):
        verify_report_approval(pr, files, 27)


@pytest.mark.parametrize("number", [True, 0, -1, 2_147_483_648])
def test_invalid_retry_number_is_rejected(tmp_path: Path, number: int) -> None:
    pr, files = _records(tmp_path)
    with pytest.raises(PolicyError, match="positive PR number"):
        verify_report_approval(pr, files, number)


def test_approval_inputs_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pr, files = _records(tmp_path)
    monkeypatch.setattr(report_approval, "MAX_APPROVAL_BYTES", 1)
    with pytest.raises(PolicyError, match="byte limit"):
        verify_report_approval(pr, files, 27)


def test_malformed_approval_input_fails_as_a_policy_error(tmp_path: Path) -> None:
    pr, files = _records(tmp_path)
    pr.write_text("not JSON")
    with pytest.raises(PolicyError, match="cannot read report approval"):
        verify_report_approval(pr, files, 27)


def test_approval_record_cannot_supply_a_publication_destination(tmp_path: Path) -> None:
    record = tmp_path / "approval.json"
    record.write_text(
        json.dumps({"number": 27, "merge_commit_sha": "a" * 40, "url": "https://evil.example"})
    )
    with pytest.raises(PolicyError, match="closed schema"):
        read_report_approval(record)
