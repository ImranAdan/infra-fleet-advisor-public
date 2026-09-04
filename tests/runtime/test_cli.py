import json
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime import cli as cli_module
from infra_fleet_advisor.runtime.cli import (
    EXIT_OK,
    EXIT_PIPELINE_ERROR,
    EXIT_POLICY_ERROR,
    EXIT_PROVENANCE_ERROR,
    EXIT_UNSAFE_OUTPUT_ERROR,
    main,
)
from infra_fleet_advisor.runtime.clock import SystemClock
from infra_fleet_advisor.runtime.composition import RunInputs, compose_and_run
from infra_fleet_advisor.runtime.fleet_feedback import (
    ADVISOR_ISSUE_LABEL,
    WONTFIX_LABEL,
    FleetIssueRecord,
    FleetIssueRecords,
)
from infra_fleet_advisor.runtime.github_issues import PublicationResult

POLICY = Path(__file__).parent.parent / "fixtures" / "policies" / "valid_policy.yaml"


def _argv(repo: Path, sha: str, output_dir: Path, prior: Path | None = None) -> list[str]:
    argv = [
        "review",
        "--checkout",
        str(repo),
        "--sha",
        sha,
        "--policy",
        str(POLICY),
        "--output-dir",
        str(output_dir),
        # Keeps the suite hermetic: the CLI now defaults to the real model.
        "--synthesizer",
        "stub",
    ]
    if prior is not None:
        argv += ["--prior-report", str(prior)]
    return argv


def test_full_run_produces_schema_valid_reports_without_cloud_creds(
    git_checkout, tmp_path: Path
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"

    exit_code = main(_argv(repo, sha, output_dir))

    assert exit_code == EXIT_OK
    payload = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["new_count"] == 1
    assert (output_dir / "report.md").exists()


def test_sha_mismatch_exits_with_provenance_error(git_checkout, tmp_path: Path) -> None:
    repo, _sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    exit_code = main(_argv(repo, "0" * 40, tmp_path / "out"))
    assert exit_code == EXIT_PROVENANCE_ERROR


def test_output_dir_inside_checkout_is_rejected(git_checkout) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    exit_code = main(_argv(repo, sha, repo / "review-output"))
    assert exit_code == EXIT_UNSAFE_OUTPUT_ERROR
    assert not (repo / "review-output").exists()


def test_second_run_reports_lifecycle_changes(git_checkout, tmp_path: Path) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    first_out = tmp_path / "first"
    main(_argv(repo, sha, first_out))

    second_out = tmp_path / "second"
    exit_code = main(_argv(repo, sha, second_out, prior=first_out / "report.json"))

    assert exit_code == EXIT_OK
    payload = json.loads((second_out / "report.json").read_text(encoding="utf-8"))
    assert payload["unchanged_count"] == 1
    assert payload["new_count"] == 0


def test_unknown_synthesizer_name_is_rejected_rather_than_defaulting(
    git_checkout, tmp_path: Path
) -> None:
    # A typo must not silently leave stub mode and spend a real model call.
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    inputs = RunInputs(
        checkout=repo,
        expected_sha=sha,
        policy_path=POLICY,
        source_label="infra-fleet-public",
        prior_report_path=None,
        synthesizer_name="stub ",
    )
    with pytest.raises(PolicyError):
        compose_and_run(inputs, SystemClock())


def test_report_signature_command_prints_a_versioned_digest(
    git_checkout, tmp_path: Path, capsys
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK

    assert main(["report-signature", "--report", str(output_dir / "report.json")]) == EXIT_OK

    output = capsys.readouterr().out.splitlines()
    assert output[-1].startswith("v2:")
    assert len(output[-1]) == 67


def test_report_signature_command_rejects_a_malformed_report(tmp_path: Path, capsys) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")

    assert main(["report-signature", "--report", str(report)]) == EXIT_POLICY_ERROR
    assert "policy error: cannot compute report signature" in capsys.readouterr().err


def test_publication_decision_command_returns_machine_readable_result(
    git_checkout, tmp_path: Path, capsys
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK
    capsys.readouterr()

    report = output_dir / "report.json"
    assert (
        main(
            [
                "publication-decision",
                "--report",
                str(report),
                "--prior-report",
                str(report),
            ]
        )
        == EXIT_OK
    )

    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "unchanged"
    assert result["marker"].startswith("<!-- infra-fleet-advisor-report-signature: v2:")


def test_publication_decision_command_reads_a_decline_marker(
    git_checkout, tmp_path: Path, capsys
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    current_dir = tmp_path / "current"
    assert main(_argv(repo, sha, current_dir)) == EXIT_OK
    capsys.readouterr()

    prior_dir = tmp_path / "prior"
    assert main(_argv(repo, sha, prior_dir)) == EXIT_OK
    prior_payload = json.loads((prior_dir / "report.json").read_text(encoding="utf-8"))
    prior_payload["coverage"][0]["evidence_count"] += 1
    (prior_dir / "report.json").write_text(json.dumps(prior_payload), encoding="utf-8")
    capsys.readouterr()

    assert main(["report-signature", "--report", str(current_dir / "report.json")]) == EXIT_OK
    signature = capsys.readouterr().out.strip()
    history = tmp_path / "pulls.json"
    history.write_text(
        json.dumps(
            [
                {
                    "number": 4,
                    "state": "closed",
                    "user": {"login": "github-actions[bot]"},
                    "body": (
                        f"prose\n<!-- infra-fleet-advisor-report-signature: {signature} -->\n"
                    ),
                    "merged_at": None,
                    "head": {
                        "ref": "advisory/latest",
                        "repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"},
                    },
                    "base": {"repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"}},
                }
            ]
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "publication-decision",
                "--report",
                str(current_dir / "report.json"),
                "--prior-report",
                str(prior_dir / "report.json"),
                "--closed-pr-history",
                str(history),
                "--repository",
                "ImranAdan/infra-fleet-advisor-public",
                "--branch",
                "advisory/latest",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["decision"] == "declined"


def test_publication_decision_command_rejects_missing_decline_body_without_path_leak(
    tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "secret-location" / "body.txt"

    assert (
        main(
            [
                "publication-decision",
                "--report",
                str(tmp_path / "unused.json"),
                "--latest-declined-pr-body",
                str(missing),
            ]
        )
        == EXIT_POLICY_ERROR
    )

    error = capsys.readouterr().err
    assert "cannot read declined pull request body: FileNotFoundError" in error
    assert str(missing) not in error


def test_remediation_skips_an_owner_accepted_trade_off(
    git_checkout, tmp_path: Path, capsys
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK
    payload = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    payload["recommendations"][0]["owner_accepted_trade_off"] = "Accepted for now."
    (output_dir / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "remediate",
                "--checkout",
                str(repo),
                "--report",
                str(output_dir / "report.json"),
            ]
        )
        == EXIT_OK
    )

    assert "no mechanically fixable findings" in capsys.readouterr().out
    assert "ignore-unfixed" in (
        repo / ".github" / "workflows" / "trivy_ignore_unfixed_bad.yml"
    ).read_text(encoding="utf-8")


def test_issue_plan_command_writes_validated_actions_without_overwriting(
    git_checkout, tmp_path: Path, capsys
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK
    capsys.readouterr()
    issue_plan = tmp_path / "issues" / "plan.json"
    argv = [
        "issue-plan",
        "--report",
        str(output_dir / "report.json"),
        "--policy",
        str(POLICY),
        "--output",
        str(issue_plan),
    ]

    assert main(argv) == EXIT_OK
    plan = json.loads(issue_plan.read_text(encoding="utf-8"))
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["action"] == "active"

    assert main(argv) == EXIT_PIPELINE_ERROR
    assert "cannot write issue plan: FileExistsError" in capsys.readouterr().err


def test_publish_issues_command_binds_validated_plan_to_adapter(
    git_checkout, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK
    capsys.readouterr()
    captured: dict[str, object] = {}

    def fake_client(repository: str) -> object:
        captured["repository"] = repository
        return object()

    def fake_publish(plan, client: object, app_bot_login: str) -> PublicationResult:
        captured["plan"] = plan
        captured["client"] = client
        captured["app_bot_login"] = app_bot_login
        return PublicationResult(created=1)

    monkeypatch.setattr(cli_module, "GhCliIssueClient", fake_client)
    monkeypatch.setattr(cli_module, "publish_issue_plan", fake_publish)

    assert (
        main(
            [
                "publish-issues",
                "--report",
                str(output_dir / "report.json"),
                "--policy",
                str(POLICY),
                "--app-bot-login",
                "advisor[bot]",
            ]
        )
        == EXIT_OK
    )

    assert captured["repository"] == "ImranAdan/infra-fleet-public"
    assert captured["app_bot_login"] == "advisor[bot]"
    assert "published 1 issue(s)" in capsys.readouterr().out


def test_publish_issues_reports_revalidation_as_a_policy_error(tmp_path: Path, capsys) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")

    assert (
        main(
            [
                "publish-issues",
                "--report",
                str(report),
                "--policy",
                str(POLICY),
                "--app-bot-login",
                "advisor[bot]",
            ]
        )
        == EXIT_POLICY_ERROR
    )
    assert "policy error: cannot read report provenance" in capsys.readouterr().err


def test_feedback_plan_command_reads_only_typed_issue_metadata(
    git_checkout, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = git_checkout("trivy_ignore_unfixed_bad.yml")
    output_dir = tmp_path / "out"
    assert main(_argv(repo, sha, output_dir)) == EXIT_OK
    capsys.readouterr()
    report_path = output_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    fingerprint = report["recommendations"][0]["fingerprint"]
    captured: dict[str, object] = {}

    class FakeFeedbackClient:
        def all_advisor_issue_records(self) -> FleetIssueRecords:
            return FleetIssueRecords(
                (
                    FleetIssueRecord(
                        number=42,
                        state="closed",
                        author="advisor[bot]",
                        labels=frozenset(
                            {
                                ADVISOR_ISSUE_LABEL,
                                WONTFIX_LABEL,
                                "advisor:tradeoff:cost",
                                f"advisor:fp:{fingerprint.removeprefix('fp_')}",
                            }
                        ),
                    ),
                ),
                complete=True,
            )

    def fake_client(repository: str) -> FakeFeedbackClient:
        captured["repository"] = repository
        return FakeFeedbackClient()

    monkeypatch.setattr(cli_module, "GhCliIssueClient", fake_client)
    output_policy = tmp_path / "feedback" / "policy.yaml"
    output_plan = tmp_path / "feedback" / "plan.json"

    assert (
        main(
            [
                "feedback-plan",
                "--report",
                str(report_path),
                "--policy",
                str(POLICY),
                "--app-bot-login",
                "advisor[bot]",
                "--output-policy",
                str(output_policy),
                "--output-plan",
                str(output_plan),
            ]
        )
        == EXIT_OK
    )

    assert captured["repository"] == "ImranAdan/infra-fleet-public"
    assert "issue prose was not imported" in output_policy.read_text(encoding="utf-8")
    assert json.loads(output_plan.read_text(encoding="utf-8"))["additions"][0]["issue_number"] == 42

    open_prs = tmp_path / "open-prs.json"
    history_prs = tmp_path / "history-prs.json"
    open_prs.write_text("[]", encoding="utf-8")
    history_prs.write_text("[]", encoding="utf-8")
    capsys.readouterr()
    assert (
        main(
            [
                "feedback-publication-decision",
                "--plan",
                str(output_plan),
                "--open-prs",
                str(open_prs),
                "--history-prs",
                str(history_prs),
                "--repository",
                "ImranAdan/infra-fleet-advisor-public",
                "--branch",
                "advisor/feedback-wontfix",
            ]
        )
        == EXIT_OK
    )
    assert json.loads(capsys.readouterr().out)["action"] == "create"
