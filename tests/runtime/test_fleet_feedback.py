import json
from pathlib import Path

import pytest

from infra_fleet_advisor.core.contracts import Recommendation, compute_fingerprint
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.report import CollectorCoverage, Report, RunProvenance
from infra_fleet_advisor.runtime.fleet_feedback import (
    ADVISOR_ISSUE_LABEL,
    CANCELLATION_MARKER,
    WONTFIX_LABEL,
    FeedbackPlan,
    FeedbackPullRequest,
    FleetIssueRecord,
    FleetIssueRecords,
    build_feedback_plan,
    decide_feedback_publication,
    read_feedback_plan,
    read_feedback_pull_requests,
    write_feedback_outputs,
)
from infra_fleet_advisor.runtime.report_writer import write_report
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_TRIVY_IGNORE_UNFIXED,
)

POLICY = Path(__file__).parent.parent / "fixtures" / "policies" / "valid_policy.yaml"
BOT = "infra-fleet-advisor[bot]"
EVIDENCE_ID = "github_actions_workflow_collector:aaaaaaaaaaaaaaaa"
SECOND_EVIDENCE_ID = "github_actions_workflow_collector:bbbbbbbbbbbbbbbb"


def _report(tmp_path: Path) -> tuple[Path, str]:
    fingerprint = compute_fingerprint("security", CONCERN_TRIVY_IGNORE_UNFIXED, (EVIDENCE_ID,))
    recommendation = Recommendation(
        fingerprint=fingerprint,
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        category="security",
        priority="medium",
        title="Trivy ignores unfixed vulnerabilities",
        summary="The gate ignores unfixed vulnerabilities.",
        evidence_ids=(EVIDENCE_ID,),
        impact="Known vulnerabilities can pass.",
        suggested_change="Remove ignore-unfixed.",
        trade_offs="Builds may block without a vendor fix.",
        confidence=0.9,
        confidence_explanation="Direct evidence.",
        status="new",
    )
    evidence = Evidence(
        evidence_id=EVIDENCE_ID,
        kind="gha_trivy_gate",
        source_path=".github/workflows/ci.yml",
        locator="jobs.security.steps[2]",
        excerpt="uses: aquasecurity/trivy-action",
        fact={"ignore_unfixed": True},
        collector_id="github_actions_workflow_collector",
        collector_version="1.1.0",
    )
    report = Report(
        provenance=RunProvenance(
            source_commit_sha="a" * 40,
            source_label="infra-fleet-public",
            advisor_version="0.1.0",
            policy_version="1.0",
            collector_versions={"github_actions_workflow_collector": "1.1.0"},
            model_identifier="stub-synthesizer-v1",
            run_started_at="2026-09-03T00:00:00Z",
        ),
        coverage=(CollectorCoverage("github_actions_workflow_collector", "ok", 1),),
        recommendations=(recommendation,),
        evidence=(evidence,),
        rejected=(),
        rejected_count=0,
        new_count=1,
        unchanged_count=0,
        resolved_count=0,
        suppressed_count=0,
    )
    return write_report(report, tmp_path / "report")[0], fingerprint


def _issue(
    fingerprint: str,
    *,
    state: str = "closed",
    author: str = BOT,
    extra_labels: frozenset[str] = frozenset({"advisor:tradeoff:cost"}),
) -> FleetIssueRecord:
    return FleetIssueRecord(
        number=42,
        state=state,
        author=author,
        labels=frozenset(
            {
                ADVISOR_ISSUE_LABEL,
                WONTFIX_LABEL,
                f"advisor:fp:{fingerprint.removeprefix('fp_')}",
                *extra_labels,
            }
        ),
    )


def _pull_request(
    plan: FeedbackPlan,
    *,
    number: int = 7,
    state: str = "open",
    author: str = "github-actions[bot]",
    body: str | None = None,
    merged: bool = False,
    head_sha: str = "a" * 40,
) -> FeedbackPullRequest:
    assert state in ("open", "closed")
    return FeedbackPullRequest(
        number=number,
        state=state,
        author=author,
        body=plan.marker if body is None else body,
        merged=merged,
        head_sha=head_sha,
    )


def _add_second_finding_for_same_concern(report: Path) -> str:
    payload = json.loads(report.read_text(encoding="utf-8"))
    second_evidence = dict(payload["evidence"][0])
    second_evidence["evidence_id"] = SECOND_EVIDENCE_ID
    second_evidence["locator"] = "jobs.second-security.steps[2]"
    payload["evidence"].append(second_evidence)

    second_recommendation = dict(payload["recommendations"][0])
    second_recommendation["evidence_ids"] = [SECOND_EVIDENCE_ID]
    second_fingerprint = compute_fingerprint(
        "security", CONCERN_TRIVY_IGNORE_UNFIXED, (SECOND_EVIDENCE_ID,)
    )
    second_recommendation["fingerprint"] = second_fingerprint
    payload["recommendations"].append(second_recommendation)
    payload["new_count"] = 2
    report.write_text(json.dumps(payload), encoding="utf-8")
    return second_fingerprint


def test_closed_wontfix_labels_produce_a_deterministic_policy_addition(
    tmp_path: Path,
) -> None:
    report, fingerprint = _report(tmp_path)

    plan = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords((_issue(fingerprint),), complete=True),
        BOT,
    )

    assert len(plan.additions) == 1
    addition = plan.additions[0]
    assert addition.concern_key == CONCERN_TRIVY_IGNORE_UNFIXED
    assert addition.reason_label == "advisor:tradeoff:cost"
    assert "#42" in addition.rationale
    assert "issue prose was not imported" in addition.rationale
    assert plan.marker == f"<!-- infra-fleet-advisor-feedback: {plan.signature} -->"
    assert plan.status == "ready"


@pytest.mark.parametrize(
    "issue",
    [
        lambda fp: _issue(fp, state="open"),
        lambda fp: _issue(fp, author="someone-else"),
        lambda fp: FleetIssueRecord(
            42,
            "closed",
            BOT,
            frozenset({ADVISOR_ISSUE_LABEL, f"advisor:fp:{fp.removeprefix('fp_')}"}),
        ),
    ],
)
def test_non_final_or_non_wontfix_issues_are_ignored(tmp_path: Path, issue) -> None:
    report, fingerprint = _report(tmp_path)

    plan = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords((issue(fingerprint),), complete=True),
        BOT,
    )

    assert plan.additions == ()


def test_wontfix_requires_exactly_one_closed_reason_label(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    issue = _issue(
        fingerprint,
        extra_labels=frozenset({"advisor:tradeoff:cost", "advisor:tradeoff:complexity"}),
    )

    with pytest.raises(PolicyError, match="one fingerprint and one trade-off reason"):
        build_feedback_plan(report, POLICY, FleetIssueRecords((issue,), True), BOT)


def test_incomplete_issue_listing_is_rejected(tmp_path: Path) -> None:
    report, _ = _report(tmp_path)

    with pytest.raises(PolicyError, match="exceeded the feedback bound"):
        build_feedback_plan(report, POLICY, FleetIssueRecords((), False), BOT)


def test_feedback_rejects_concern_level_policy_ambiguity(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    _add_second_finding_for_same_concern(report)

    with pytest.raises(PolicyError, match="multiple active findings"):
        build_feedback_plan(
            report,
            POLICY,
            FleetIssueRecords((_issue(fingerprint),), True),
            BOT,
        )


def test_feedback_signature_is_order_independent_and_reason_sensitive(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    selected = _issue(fingerprint)
    stale = _issue("fp_" + "f" * 24)

    first = build_feedback_plan(report, POLICY, FleetIssueRecords((selected, stale), True), BOT)
    reordered = build_feedback_plan(report, POLICY, FleetIssueRecords((stale, selected), True), BOT)
    changed_reason = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords(
            (_issue(fingerprint, extra_labels=frozenset({"advisor:tradeoff:complexity"})),),
            True,
        ),
        BOT,
    )

    assert first.signature == reordered.signature
    assert first.signature != changed_reason.signature


def test_feedback_outputs_preserve_policy_comments_and_validate_result(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    commented_policy = tmp_path / "policy.yaml"
    commented_policy.write_text(
        "# Advisor policy for reviewing the fleet.\n" + POLICY.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    plan = build_feedback_plan(
        report,
        commented_policy,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )
    output_policy = tmp_path / "output" / "policy.yaml"
    output_plan = tmp_path / "output" / "feedback.json"

    write_feedback_outputs(plan, commented_policy, output_policy, output_plan)

    updated = output_policy.read_text(encoding="utf-8")
    assert "# Advisor policy for reviewing" in updated
    assert 'version: "feedback-v1:' in updated
    assert "concern_key: trivy_ignore_unfixed" in updated
    assert "issue prose was not imported" in updated
    assert json.loads(output_plan.read_text(encoding="utf-8"))["signature"] == plan.signature


def test_feedback_appends_to_existing_trade_offs_and_versions_deterministically(
    tmp_path: Path,
) -> None:
    report, fingerprint = _report(tmp_path)
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            "accepted_trade_offs: []",
            "accepted_trade_offs:\n"
            "  - concern_key: wildcard_iam_permissions\n"
            "    rationale: Existing owner decision.",
        ),
        encoding="utf-8",
    )
    plan = build_feedback_plan(
        report,
        policy,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    write_feedback_outputs(plan, policy, first, tmp_path / "first.json")
    write_feedback_outputs(plan, policy, second, tmp_path / "second.json")

    assert first.read_bytes() == second.read_bytes()
    updated = first.read_text(encoding="utf-8")
    assert "concern_key: wildcard_iam_permissions" in updated
    assert f"concern_key: {CONCERN_TRIVY_IGNORE_UNFIXED}" in updated


def test_empty_feedback_writes_a_plan_but_not_a_policy(tmp_path: Path) -> None:
    report, _ = _report(tmp_path)
    plan = build_feedback_plan(report, POLICY, FleetIssueRecords((), True), BOT)
    output_policy = tmp_path / "policy.yaml"
    output_plan = tmp_path / "feedback.json"

    write_feedback_outputs(plan, POLICY, output_policy, output_plan)

    assert output_plan.exists()
    assert not output_policy.exists()


def test_policy_version_mismatch_waits_for_a_fresh_report(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    changed_policy = tmp_path / "changed-policy.yaml"
    changed_policy.write_text(
        POLICY.read_text(encoding="utf-8").replace('version: "1.0"', 'version: "1.1"'),
        encoding="utf-8",
    )

    plan = build_feedback_plan(
        report,
        changed_policy,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )

    assert plan.status == "awaiting_report_refresh"
    assert plan.additions == ()


def test_feedback_plan_round_trip_rejects_tampering(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    plan = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )
    plan_path = tmp_path / "plan.json"
    output_policy = tmp_path / "policy.yaml"
    write_feedback_outputs(plan, POLICY, output_policy, plan_path)

    assert read_feedback_plan(plan_path) == plan

    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["additions"][0]["rationale"] = "Imported issue prose"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PolicyError, match="failed deterministic validation"):
        read_feedback_plan(tampered)


def test_feedback_pull_request_reader_validates_exact_source(tmp_path: Path) -> None:
    pull_requests = tmp_path / "pulls.json"
    raw = {
        "number": 7,
        "state": "closed",
        "user": {"login": "github-actions[bot]"},
        "body": "body",
        "merged_at": None,
        "head": {
            "ref": "advisor/feedback-wontfix",
            "sha": "a" * 40,
            "repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"},
        },
        "base": {"repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"}},
    }
    pull_requests.write_text(json.dumps([raw]), encoding="utf-8")

    records = read_feedback_pull_requests(
        pull_requests,
        repository="ImranAdan/infra-fleet-advisor-public",
        branch="advisor/feedback-wontfix",
        maximum=1,
    )
    assert records[0].number == 7

    raw["head"]["repo"]["full_name"] = "attacker/fork"
    pull_requests.write_text(json.dumps([raw]), encoding="utf-8")
    with pytest.raises(PolicyError, match="failed validation"):
        read_feedback_pull_requests(
            pull_requests,
            repository="ImranAdan/infra-fleet-advisor-public",
            branch="advisor/feedback-wontfix",
            maximum=1,
        )


def test_feedback_publication_decision_matrix(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    ready = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )
    empty = build_feedback_plan(report, POLICY, FleetIssueRecords((), True), BOT)
    open_pr = _pull_request(ready)

    assert decide_feedback_publication(empty, (), (), branch_tip=None).action == "none"
    cancelled = decide_feedback_publication(empty, (open_pr,), (open_pr,), branch_tip="a" * 40)
    assert (cancelled.action, cancelled.open_pr_number) == ("cancel", 7)
    assert (
        decide_feedback_publication(ready, (open_pr,), (open_pr,), branch_tip="a" * 40).reason
        == "already_open"
    )
    assert (
        decide_feedback_publication(ready, (open_pr,), (open_pr,), branch_tip=None).action
        == "update"
    )

    changed_open = _pull_request(ready, body="older feedback marker")
    assert (
        decide_feedback_publication(
            ready, (changed_open,), (changed_open,), branch_tip="a" * 40
        ).action
        == "update"
    )

    declined = _pull_request(ready, state="closed")
    assert (
        decide_feedback_publication(ready, (), (declined,), branch_tip="a" * 40).reason
        == "declined"
    )
    workflow_cancelled = _pull_request(
        ready,
        state="closed",
        body=f"{ready.marker}\n{CANCELLATION_MARKER}",
    )
    assert (
        decide_feedback_publication(ready, (), (workflow_cancelled,), branch_tip="a" * 40).action
        == "create"
    )


def test_feedback_publication_rejects_unowned_branch_state(tmp_path: Path) -> None:
    report, fingerprint = _report(tmp_path)
    plan = build_feedback_plan(
        report,
        POLICY,
        FleetIssueRecords((_issue(fingerprint),), True),
        BOT,
    )
    impostor = _pull_request(plan, author="someone-else")

    with pytest.raises(PolicyError, match="not workflow-owned"):
        decide_feedback_publication(plan, (impostor,), (), branch_tip="a" * 40)
    with pytest.raises(PolicyError, match="cannot be proven"):
        decide_feedback_publication(plan, (), (), branch_tip="a" * 40)
    moved_branch = _pull_request(plan, state="closed", head_sha="b" * 40)
    with pytest.raises(PolicyError, match="cannot be proven"):
        decide_feedback_publication(
            plan,
            (),
            (moved_branch,),
            branch_tip="a" * 40,
        )

    recovered = decide_feedback_publication(
        plan,
        (),
        (),
        branch_tip="a" * 40,
        branch_matches_plan=True,
    )
    assert recovered.action == "create"


def test_empty_feedback_does_not_claim_or_mutate_an_orphan_branch(tmp_path: Path) -> None:
    report, _ = _report(tmp_path)
    plan = build_feedback_plan(report, POLICY, FleetIssueRecords((), True), BOT)

    decision = decide_feedback_publication(plan, (), (), branch_tip="a" * 40)

    assert decision.action == "none"
