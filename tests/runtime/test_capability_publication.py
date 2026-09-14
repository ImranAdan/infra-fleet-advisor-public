import json
from dataclasses import replace
from pathlib import Path

import pytest

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.core.errors import IssuePublicationError, PolicyError
from infra_fleet_advisor.core.intent import IntentEvaluation, IntentEvaluationStatus
from infra_fleet_advisor.core.report import Report, RunProvenance
from infra_fleet_advisor.runtime import capability_publication
from infra_fleet_advisor.runtime.capability_publication import (
    ADVISOR_REPOSITORY,
    CAPABILITY_GAP_LABEL,
    build_capability_plan,
    publish_capability_plan,
    write_capability_plan,
)
from infra_fleet_advisor.runtime.report_writer import write_report
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY

POLICY = Path(__file__).parent.parent / "fixtures" / "policies" / "valid_policy.yaml"
SOURCE_SHA = "a" * 40


def _intent_directory(
    tmp_path: Path,
    *,
    check_key: str | None = None,
    priority: str | None = None,
    category: str = "security",
    statement: str = "The fleet notifies @ops through https://example.invalid when checks fail.",
) -> Path:
    directory = tmp_path / "intent"
    directory.mkdir(parents=True)
    evaluation: list[str] = []
    if check_key is not None or priority is not None:
        evaluation = ["", "### Evaluation", ""]
        if check_key is not None:
            evaluation.append(f"- Check: `{check_key}`")
        if priority is not None:
            evaluation.append(f"- Priority: `{priority}`")
    lines = [
        "# Test intent",
        "",
        "- Format: `1`",
        "- Intent ID: `test_intent`",
        "- Version: `1.0`",
        f"- Category: `{category}`",
        "",
        "## T-001 · Test proposition",
        "",
        "### Intent",
        "",
        statement,
        *evaluation,
        "",
    ]
    (directory / "test.md").write_text("\n".join(lines), encoding="utf-8")
    return directory


def _report(
    tmp_path: Path,
    intent_dir: Path,
    *,
    status: IntentEvaluationStatus,
    reason: str,
    check_key: str | None = None,
    priority: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> Path:
    catalog = load_intent_catalog(intent_dir, TAXONOMY)
    proposition = catalog.propositions[0]
    report = Report(
        provenance=RunProvenance(
            source_commit_sha=SOURCE_SHA,
            source_label="infra-fleet-public",
            advisor_version="0.1.0",
            policy_version="1.0",
            collector_versions={},
            model_identifier="stub-synthesizer-v1",
            run_started_at="2026-09-10T00:00:00Z",
            intent_digest=catalog.digest,
        ),
        coverage=(),
        recommendations=(),
        evidence=(),
        rejected=(),
        rejected_count=0,
        new_count=0,
        unchanged_count=0,
        resolved_count=0,
        suppressed_count=0,
        intent_evaluations=(
            IntentEvaluation(
                document_id=proposition.document_id,
                proposition_id=proposition.proposition_id,
                category=proposition.category,
                priority=priority,
                statement=proposition.statement,
                check_key=check_key,
                status=status,
                evidence_ids=evidence_ids,
                reason=reason,
            ),
        ),
    )
    report_path, _markdown_path = write_report(report, tmp_path / "report")
    return report_path


def test_missing_check_becomes_inert_advisor_capability_work(tmp_path: Path) -> None:
    intent_dir = _intent_directory(
        tmp_path,
        priority="high",
        statement="- [ ] Notify @ops through https://example.invalid when checks fail.",
    )
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
        priority="high",
    )

    plan = build_capability_plan(report, POLICY, intent_dir)

    assert plan.target_repository == ADVISOR_REPOSITORY
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.action == "active"
    assert action.fingerprint.startswith("cap_")
    assert action.fingerprint_label.startswith("advisor:intent:")
    assert CAPABILITY_GAP_LABEL not in action.fingerprint_label
    assert "not evidence that the fleet violates the intent" in action.body
    assert "\\- \\[ \\] Notify" in action.body
    assert "&#64;ops" in action.body
    assert "https&#58;//example.invalid" in action.body
    assert "A later merged report is required" in action.body
    assert action.reactivation_marker is not None
    assert action.reactivation_comment is not None
    assert action.reactivation_marker in action.reactivation_comment


@pytest.mark.parametrize(
    ("check_key", "priority", "reason"),
    [
        ("not_registered", None, "check_not_registered"),
        ("github_actions_uses_oidc", "high", "collector_cannot_prove_satisfaction"),
    ],
)
def test_unsupported_registered_state_becomes_capability_work(
    tmp_path: Path,
    check_key: str,
    priority: str | None,
    reason: str,
) -> None:
    intent_dir = _intent_directory(tmp_path, check_key=check_key)
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason=reason,
        check_key=check_key,
        priority=priority,
    )

    assert build_capability_plan(report, POLICY, intent_dir).actions[0].action == "active"


def test_supported_or_policy_disabled_proposition_resolves_capability_work(
    tmp_path: Path,
) -> None:
    supported_root = tmp_path / "supported"
    intent_dir = _intent_directory(
        supported_root,
        check_key="trivy_does_not_ignore_unfixed",
    )
    report = _report(
        supported_root,
        intent_dir,
        status="satisfied",
        reason="complete_evidence_supports_intent",
        check_key="trivy_does_not_ignore_unfixed",
        priority="medium",
    )
    supported = build_capability_plan(report, POLICY, intent_dir).actions[0]

    disabled_root = tmp_path / "disabled"
    disabled_intent = _intent_directory(disabled_root, category="cost")
    disabled_report = _report(
        disabled_root,
        disabled_intent,
        status="declared_unverified",
        reason="category_not_enabled_by_policy",
    )
    disabled = build_capability_plan(disabled_report, POLICY, disabled_intent).actions[0]

    assert supported.action == "resolved"
    assert disabled.action == "resolved"


def test_capability_identity_survives_intent_wording_changes(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    first_intent = _intent_directory(first_root, statement="First wording.")
    first_report = _report(
        first_root,
        first_intent,
        status="declared_unverified",
        reason="check_not_declared",
    )
    second_root = tmp_path / "second"
    second_intent = _intent_directory(second_root, statement="Revised wording.")
    second_report = _report(
        second_root,
        second_intent,
        status="declared_unverified",
        reason="check_not_declared",
    )

    first = build_capability_plan(first_report, POLICY, first_intent).actions[0]
    second = build_capability_plan(second_report, POLICY, second_intent).actions[0]

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint_marker == second.fingerprint_marker
    assert first.content_marker != second.content_marker


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["intent_evaluations"].clear(), "exactly one evaluation"),
        (
            lambda payload: payload["intent_evaluations"][0].update({"statement": "tampered"}),
            "does not match the current catalog",
        ),
        (
            lambda payload: payload["intent_evaluations"][0].update({"status": "satisfied"}),
            "cannot read report intent evaluations",
        ),
        (
            lambda payload: payload["intent_evaluations"][0].update({"unknown": "field"}),
            "cannot read report intent evaluations",
        ),
    ],
)
def test_capability_plan_rejects_malformed_or_tampered_evaluations(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    intent_dir = _intent_directory(tmp_path)
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    mutation(payload)
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PolicyError, match=message):
        build_capability_plan(report, POLICY, intent_dir)


def test_capability_plan_rejects_stale_intent_digest(tmp_path: Path) -> None:
    intent_dir = _intent_directory(tmp_path)
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["provenance"]["intent_digest"] = "intent-md-v1:" + "0" * 64
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PolicyError, match="intent digest does not match"):
        build_capability_plan(report, POLICY, intent_dir)


def test_registered_check_cannot_be_reported_as_missing(tmp_path: Path) -> None:
    intent_dir = _intent_directory(tmp_path, check_key="github_actions_uses_oidc")
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
        check_key="github_actions_uses_oidc",
        priority="high",
    )

    with pytest.raises(PolicyError, match="contradicts the registered check"):
        build_capability_plan(report, POLICY, intent_dir)


def test_capability_plan_enforces_body_bound_and_no_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent_dir = _intent_directory(tmp_path)
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
    )
    monkeypatch.setattr(capability_publication, "MAX_CAPABILITY_BODY_CHARS", 10)
    with pytest.raises(PolicyError, match="body exceeds 10"):
        build_capability_plan(report, POLICY, intent_dir)

    monkeypatch.setattr(capability_publication, "MAX_CAPABILITY_BODY_CHARS", 20_000)
    plan = build_capability_plan(report, POLICY, intent_dir)
    output = tmp_path / "plans" / "capabilities.json"
    write_capability_plan(plan, output)
    with pytest.raises(FileExistsError):
        write_capability_plan(plan, output)


def test_capability_publisher_rejects_a_plan_for_another_repository(tmp_path: Path) -> None:
    intent_dir = _intent_directory(tmp_path)
    report = _report(
        tmp_path,
        intent_dir,
        status="declared_unverified",
        reason="check_not_declared",
    )
    plan = build_capability_plan(report, POLICY, intent_dir)

    with pytest.raises(IssuePublicationError, match="unsupported repository"):
        publish_capability_plan(
            replace(plan, target_repository="someone/else"),
            object(),  # type: ignore[arg-type]
            "github-actions[bot]",
        )
