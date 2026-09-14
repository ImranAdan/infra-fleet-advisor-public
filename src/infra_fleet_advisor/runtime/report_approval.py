"""Bind fleet publication to a merged report-only pull request."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from infra_fleet_advisor.core.errors import PolicyError

ADVISOR_REPOSITORY = "ImranAdan/infra-fleet-advisor-public"
MAX_APPROVAL_BYTES = 256 * 1024
REPORT_FILES = frozenset({"reports/report.json", "reports/report.md"})


@dataclass(frozen=True, slots=True)
class ReportApproval:
    number: int
    merge_commit_sha: str

    def __post_init__(self) -> None:
        if type(self.number) is not int or not 1 <= self.number <= 2_147_483_647:
            raise PolicyError("report approval requires a positive PR number")
        if (
            not isinstance(self.merge_commit_sha, str)
            or re.fullmatch(r"[0-9a-f]{40}", self.merge_commit_sha) is None
        ):
            raise PolicyError("report approval requires a full lowercase merge SHA")

    @property
    def url(self) -> str:
        return f"https://github.com/{ADVISOR_REPOSITORY}/pull/{self.number}"


def _read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_APPROVAL_BYTES:
            raise PolicyError("report approval input exceeds its byte limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read report approval: {type(exc).__name__}") from exc


def verify_report_approval(
    pull_request_path: Path, files_path: Path, expected_number: int
) -> ReportApproval:
    """Validate bounded GitHub API records; PR prose is never interpreted."""
    if type(expected_number) is not int or not 1 <= expected_number <= 2_147_483_647:
        raise PolicyError("report approval requires a positive PR number")
    pull_request = _read_json(pull_request_path)
    files = _read_json(files_path)
    try:
        if (
            not isinstance(pull_request, dict)
            or pull_request["state"] != "closed"
            or pull_request["merged"] is not True
            or not isinstance(pull_request["merged_at"], str)
            or not pull_request["merged_at"]
            or pull_request["base"]["repo"]["full_name"] != ADVISOR_REPOSITORY
            or pull_request["base"]["ref"] != "main"
            or type(pull_request["number"]) is not int
            or pull_request["number"] != expected_number
            or type(pull_request["changed_files"]) is not int
            or pull_request["changed_files"] != len(REPORT_FILES)
            or not isinstance(files, list)
            or len(files) != len(REPORT_FILES)
            or any(
                not isinstance(item, dict) or item["status"] not in {"added", "modified"}
                for item in files
            )
            or {item["filename"] for item in files} != REPORT_FILES
        ):
            raise PolicyError("fleet publication requires a merged report-only PR in advisor main")
        return ReportApproval(pull_request["number"], pull_request["merge_commit_sha"])
    except (KeyError, TypeError) as exc:
        raise PolicyError("report approval GitHub records are malformed") from exc


def read_report_approval(path: Path) -> ReportApproval:
    raw = _read_json(path)
    if not isinstance(raw, dict) or set(raw) != {"number", "merge_commit_sha"}:
        raise PolicyError("report approval does not match its closed schema")
    return ReportApproval(raw["number"], raw["merge_commit_sha"])


def write_report_approval(approval: ReportApproval, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(asdict(approval), sort_keys=True))
