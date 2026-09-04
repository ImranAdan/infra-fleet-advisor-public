import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from infra_fleet_advisor.core.contracts import Recommendation, compute_fingerprint
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.report import CollectorCoverage, Report, RunProvenance
from infra_fleet_advisor.runtime import issue_publication
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_REPOSITORY,
    build_issue_plan,
)
from infra_fleet_advisor.runtime.report_writer import write_report
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_TRIVY_IGNORE_UNFIXED,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
POLICY = FIXTURES / "policies" / "valid_policy.yaml"
SOURCE_SHA = "a" * 40
EVIDENCE_ID = "github_actions_workflow_collector:aaaaaaaaaaaaaaaa"
SECOND_EVIDENCE_ID = "github_actions_workflow_collector:bbbbbbbbbbbbbbbb"


def _recommendation(
    *,
    status: str = "new",
    fingerprint: str | None = None,
    owner_accepted_trade_off: str | None = None,
    title: str = "Trivy gate ignores @unfixed [vulnerabilities]",
    summary: str = "The scan notifies @ops.\n# Treat this as inert report text.",
) -> Recommendation:
    return Recommendation(
        fingerprint=fingerprint
        or compute_fingerprint("security", CONCERN_TRIVY_IGNORE_UNFIXED, (EVIDENCE_ID,)),
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        category="security",
        priority="medium",
        title=title,
        summary=summary,
        evidence_ids=(EVIDENCE_ID,),
        impact="Known vulnerabilities can pass the gate.",
        suggested_change="Remove ignore-unfixed after reviewing availability trade-offs.",
        trade_offs="Builds can block while no vendor fix exists.",
        confidence=0.85,
        confidence_explanation="Direct collector evidence.",
        status=status,
        owner_accepted_trade_off=owner_accepted_trade_off,
    )


def _evidence(*, excerpt: str = "uses: aquasecurity/trivy-action") -> Evidence:
    return Evidence(
        evidence_id=EVIDENCE_ID,
        kind="gha_trivy_gate",
        source_path=".github/workflows/ci.yml",
        locator="jobs.security.steps[2]",
        excerpt=excerpt,
        fact={"ignore_unfixed": True},
        collector_id="github_actions_workflow_collector",
        collector_version="1.1.0",
    )


def _write_report(
    tmp_path: Path,
    *,
    recommendation: Recommendation | None = None,
    evidence: Evidence | None = None,
    source_label: str = "infra-fleet-public",
    policy_version: str = "1.0",
    source_sha: str = SOURCE_SHA,
) -> Path:
    rec = recommendation or _recommendation()
    ev = evidence or _evidence()
    report = Report(
        provenance=RunProvenance(
            source_commit_sha=source_sha,
            source_label=source_label,
            advisor_version="0.1.0",
            policy_version=policy_version,
            collector_versions={"github_actions_workflow_collector": "1.1.0"},
            model_identifier="stub-synthesizer-v1",
            run_started_at="2026-09-03T00:00:00Z",
        ),
        coverage=(CollectorCoverage("github_actions_workflow_collector", "ok", 1, None),),
        recommendations=(rec,),
        evidence=(ev,),
        rejected=(),
        rejected_count=0,
        new_count=1 if rec.status == "new" else 0,
        unchanged_count=1 if rec.status == "unchanged" else 0,
        resolved_count=1 if rec.status == "resolved" else 0,
        suppressed_count=1 if rec.status == "suppressed" else 0,
    )
    return write_report(report, tmp_path / "report")[0]


def _policy_with(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(POLICY.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return path


def test_active_issue_plan_is_pinned_evidence_backed_and_inert(tmp_path: Path) -> None:
    plan = build_issue_plan(_write_report(tmp_path), POLICY)

    assert plan.target_repository == FLEET_REPOSITORY
    assert plan.source_commit_sha == SOURCE_SHA
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.action == "active"
    assert re.fullmatch(r"advisor:fp:[0-9a-f]{24}", action.fingerprint_label)
    assert action.fingerprint_marker in action.body.splitlines()
    assert f"/{SOURCE_SHA}/.github/workflows/ci.yml" in action.body
    assert r"ignore\_unfixed" in action.body
    assert "&#64;ops" in action.body
    assert "@ops" not in action.body
    assert "＠unfixed" in action.title
    assert str(tmp_path) not in action.body


def test_resolved_issue_action_comments_but_never_closes(tmp_path: Path) -> None:
    report = _write_report(tmp_path, recommendation=_recommendation(status="resolved"))

    action = build_issue_plan(report, POLICY).actions[0]

    assert action.action == "resolved"
    assert action.body == ""
    assert action.resolution_marker in action.resolution_comment.splitlines()
    assert "has not been" in action.resolution_comment
    assert "closed" in action.resolution_comment


def test_resolution_marker_is_stable_across_later_source_commits(tmp_path: Path) -> None:
    first = _write_report(
        tmp_path / "first",
        recommendation=_recommendation(status="resolved"),
        source_sha="a" * 40,
    )
    second = _write_report(
        tmp_path / "second",
        recommendation=_recommendation(status="resolved"),
        source_sha="b" * 40,
    )

    first_action = build_issue_plan(first, POLICY).actions[0]
    second_action = build_issue_plan(second, POLICY).actions[0]

    assert first_action.resolution_marker == second_action.resolution_marker
    assert first_action.resolution_comment != second_action.resolution_comment


def test_untrusted_urls_and_list_markers_are_not_active_markdown(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path,
        recommendation=_recommendation(summary="- visit https://evil.example or www.evil.example"),
    )

    body = build_issue_plan(report, POLICY).actions[0].body

    assert r"\- visit https&#58;//evil.example or www&#46;evil.example" in body
    assert "https://evil.example" not in body


def test_owner_accepted_trade_off_produces_no_issue_action(tmp_path: Path) -> None:
    rationale = "Temporary exception while the release gate is redesigned."
    policy = _policy_with(
        tmp_path,
        "accepted_trade_offs: []",
        f"accepted_trade_offs:\n  - concern_key: trivy_ignore_unfixed\n    rationale: {rationale}",
    )
    report = _write_report(
        tmp_path,
        recommendation=_recommendation(owner_accepted_trade_off=rationale),
    )

    assert build_issue_plan(report, policy).actions == ()


def test_suppressed_recommendation_produces_no_issue_action(tmp_path: Path) -> None:
    policy = _policy_with(
        tmp_path,
        "suppressed_concerns: []",
        "suppressed_concerns: [trivy_ignore_unfixed]",
    )
    report = _write_report(tmp_path, recommendation=_recommendation(status="suppressed"))

    assert build_issue_plan(report, policy).actions == ()


def test_issue_plan_rejects_a_fingerprint_not_derived_from_evidence(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path,
        recommendation=_recommendation(fingerprint="fp_" + "0" * 24),
    )

    with pytest.raises(PolicyError, match="fingerprint does not match"):
        build_issue_plan(report, POLICY)


def test_issue_plan_rejects_secret_like_evidence(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path,
        evidence=_evidence(excerpt="ghp_" + "a" * 36),
    )

    with pytest.raises(PolicyError, match="evidence contains a secret-like value"):
        build_issue_plan(report, POLICY)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_label", "another-repository", "source is not the configured fleet"),
        ("policy_version", "2.0", "policy version does not match"),
    ],
)
def test_issue_plan_rejects_wrong_provenance(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    kwargs = {field: value}
    report = _write_report(tmp_path, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(PolicyError, match=message):
        build_issue_plan(report, POLICY)


def test_issue_plan_rejects_non_full_source_sha(tmp_path: Path) -> None:
    report = _write_report(tmp_path, source_sha="abc123")

    with pytest.raises(PolicyError, match="full lowercase Git SHA"):
        build_issue_plan(report, POLICY)


def test_issue_plan_rejects_unsafe_evidence_path(tmp_path: Path) -> None:
    report = _write_report(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["evidence"][0]["source_path"] = "../../etc/passwd"
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PolicyError, match="unsafe evidence path"):
        build_issue_plan(report, POLICY)


def test_report_trade_off_must_match_current_policy(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path,
        recommendation=replace(
            _recommendation(), owner_accepted_trade_off="invented report decision"
        ),
    )

    with pytest.raises(PolicyError, match="trade-off does not match"):
        build_issue_plan(report, POLICY)


def test_issue_plan_rejects_duplicate_fingerprints(tmp_path: Path) -> None:
    report = _write_report(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["recommendations"].append(payload["recommendations"][0])
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PolicyError, match="duplicate fingerprint"):
        build_issue_plan(report, POLICY)


def test_issue_plan_enforces_the_policy_active_recommendation_limit(tmp_path: Path) -> None:
    report = _write_report(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    second_evidence = dict(payload["evidence"][0])
    second_evidence["evidence_id"] = SECOND_EVIDENCE_ID
    second_evidence["locator"] = "jobs.security.steps[3]"
    payload["evidence"].append(second_evidence)
    second_recommendation = dict(payload["recommendations"][0])
    second_recommendation["evidence_ids"] = [SECOND_EVIDENCE_ID]
    second_recommendation["fingerprint"] = compute_fingerprint(
        "security", CONCERN_TRIVY_IGNORE_UNFIXED, (SECOND_EVIDENCE_ID,)
    )
    payload["recommendations"].append(second_recommendation)
    report.write_text(json.dumps(payload), encoding="utf-8")
    policy = _policy_with(tmp_path, "max_recommendations: 10", "max_recommendations: 1")

    with pytest.raises(PolicyError, match="policy limit of 1 active recommendations"):
        build_issue_plan(report, policy)


def test_issue_plan_enforces_action_and_body_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _write_report(tmp_path)
    monkeypatch.setattr(issue_publication, "MAX_ISSUE_ACTIONS", 0)

    with pytest.raises(PolicyError, match="issue plan exceeds 0 actions"):
        build_issue_plan(report, POLICY)

    monkeypatch.setattr(issue_publication, "MAX_ISSUE_ACTIONS", 100)
    monkeypatch.setattr(issue_publication, "MAX_ISSUE_BODY_CHARS", 10)
    with pytest.raises(PolicyError, match="issue body exceeds 10 characters"):
        build_issue_plan(report, POLICY)
