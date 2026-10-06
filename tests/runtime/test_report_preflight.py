"""The advisory workflow must refuse to open a report PR it could not publish.

Report PR #66 merged as a decision record and only then failed issue
publication. The workflow now builds the prospective issue plan before any PR
step; these tests pin both the step's placement and the command's verdict, so
a later workflow edit cannot quietly recreate the post-merge failure.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.runtime.cli import EXIT_OK, EXIT_POLICY_ERROR, main

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "fleet-advisory.yml"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
POLICY = ROOT / "tests" / "fixtures" / "policies" / "valid_policy.yaml"
INTENTS = ROOT / "tests" / "fixtures" / "intents"
PREFLIGHT = "Validate the prospective fleet issue plan"
REVIEW = "Run the review"
PR_STEPS = ("Compose the pull request body", "Open or update the advisory pull request")


def test_report_only_prs_relay_dispatched_quality_into_required_statuses() -> None:
    """A bot report gets exact-head evidence without an approval-required run."""
    workflow = yaml.safe_load(QUALITY_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    advisory = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert "reports/**" in triggers["pull_request"]["paths-ignore"]
    assert "pr_number" in triggers["workflow_dispatch"]["inputs"]
    assert advisory["permissions"]["statuses"] == "write"


def test_quality_is_two_isolated_complete_checks() -> None:
    """Tests and merge gates must stay complete and on separate runners."""
    workflow = yaml.safe_load(QUALITY_WORKFLOW.read_text(encoding="utf-8"))
    assert set(workflow["jobs"]) == {"quality", "gates"}
    quality = workflow["jobs"]["quality"]
    gates = workflow["jobs"]["gates"]
    assert "Advisor Quality (dispatched)" in quality["name"]
    assert "Advisor Gates (dispatched)" in gates["name"]
    quality_names = {step.get("name") for step in quality["steps"]}
    gate_names = {step.get("name") for step in gates["steps"]}
    assert "Run lint, types and unit tests" in quality_names
    gated_phases = {
        "Run check drills",
        "Compare the base advisor with this change",
        "Lint workflows",
        "Scan source and dependencies",
    }
    assert gated_phases <= gate_names
    assert gated_phases.isdisjoint(quality_names)


def test_report_delivery_waits_for_quality_then_wakes_autonomous_merge() -> None:
    [step] = [s for s in _advise_steps() if s.get("name") == PR_STEPS[-1]]
    script = step["run"]

    quality = script.index("gh workflow run quality.yml")
    wait = script.index("gh run watch")
    bridge = script.index("report_status_bridge.py")
    merge = script.index("gh workflow run autonomous-merge.yml")
    assert quality < wait < bridge < merge
    assert "--exit-status" in script
    assert "*[!0-9]*" in script
    assert 'merge_state="UNKNOWN"' in script


def _advise_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"]["advise"]["steps"])


def _placeholder_approval() -> str:
    """The exact approval JSON the workflow writes, so test and workflow cannot drift."""
    [step] = [s for s in _advise_steps() if s.get("name") == PREFLIGHT]
    match = re.search(r"<<'JSON'\n(.*?)\n\s*JSON", step["run"], re.DOTALL)
    assert match, "preflight no longer writes its placeholder approval"
    return match.group(1).strip()


def test_preflight_runs_after_the_review_and_before_any_pr_step() -> None:
    names = [step.get("name") for step in _advise_steps()]
    preflight = names.index(PREFLIGHT)

    assert names.index(REVIEW) < preflight
    assert all(preflight < names.index(name) for name in PR_STEPS)
    step = _advise_steps()[preflight]
    # Nothing may skip the gate or let the job continue past its failure.
    assert "if" not in step
    assert "continue-on-error" not in step
    assert "infra-fleet-advisor issue-plan" in step["run"]
    assert "--approval" in step["run"]


def _review(git_checkout, tmp_path: Path) -> Path:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output = tmp_path / "review"
    argv = [
        "review", "--checkout", str(repo), "--sha", sha, "--policy", str(POLICY),
        "--intent-dir", str(INTENTS), "--output-dir", str(output), "--synthesizer", "stub",
    ]  # fmt: skip
    assert main(argv) == EXIT_OK
    return output / "report.json"


def _issue_plan(report: Path, tmp_path: Path, name: str) -> int:
    approval = tmp_path / f"{name}-approval.json"
    approval.write_text(_placeholder_approval(), encoding="utf-8")
    return main(
        [
            "issue-plan",
            "--report",
            str(report),
            "--policy",
            str(POLICY),
            "--intent-dir",
            str(INTENTS),
            "--approval",
            str(approval),
            "--output",
            str(tmp_path / f"{name}-plan.json"),
        ]  # fmt: skip
    )


def test_preflight_accepts_a_publishable_report(git_checkout, tmp_path: Path) -> None:
    report = _review(git_checkout, tmp_path)

    assert _issue_plan(report, tmp_path, "valid") == EXIT_OK


def test_preflight_rejects_a_recommendation_its_evidence_no_longer_supports(
    git_checkout, tmp_path: Path, capsys
) -> None:
    report = _review(git_checkout, tmp_path)
    document = json.loads(report.read_text(encoding="utf-8"))
    # The #66 failure: a cited evidence record whose facts contradict the finding.
    cited = {eid for rec in document["recommendations"] for eid in rec["evidence_ids"]}
    for evidence in document["evidence"]:
        if evidence["evidence_id"] in cited:
            evidence["fact"] = {key: not value if isinstance(value, bool) else value
                                for key, value in evidence["fact"].items()}  # fmt: skip
    report.write_text(json.dumps(document), encoding="utf-8")

    capsys.readouterr()
    assert _issue_plan(report, tmp_path, "invalid") == EXIT_POLICY_ERROR
    assert "invalid recommendation" in capsys.readouterr().err
