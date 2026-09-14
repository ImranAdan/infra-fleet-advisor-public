import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.issue_publication import FLEET_SOURCE_LABEL
from infra_fleet_advisor.runtime.report_writer import read_report_metadata
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY


@dataclass(frozen=True, slots=True)
class ReportReadiness:
    ready: bool
    reason: Literal["current", "report_missing", "policy_changed", "intent_changed"]


def check_report_readiness(
    report_path: Path, policy_path: Path, intent_dir: Path
) -> ReportReadiness:
    """Wait for a current ratified report; publication still validates its full contents."""
    policy = load_policy(policy_path, TAXONOMY)
    catalog = load_intent_catalog(intent_dir, TAXONOMY)
    if not report_path.exists():
        return ReportReadiness(False, "report_missing")
    metadata = read_report_metadata(report_path)
    if metadata.source_label != FLEET_SOURCE_LABEL:
        raise PolicyError("report source is not the configured fleet")
    if re.fullmatch(r"[0-9a-f]{40}", metadata.source_commit_sha) is None:
        raise PolicyError("report source commit must be a full lowercase Git SHA")
    if metadata.policy_version != policy.version:
        return ReportReadiness(False, "policy_changed")
    if metadata.intent_digest != catalog.digest:
        return ReportReadiness(False, "intent_changed")
    return ReportReadiness(True, "current")
