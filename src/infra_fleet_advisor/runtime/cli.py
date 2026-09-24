import argparse
import json
import subprocess  # noqa: S404 - only for CalledProcessError
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from infra_fleet_advisor.core.errors import AdvisorError, PolicyError, ProvenanceError
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.runtime.capability_publication import (
    build_capability_plan,
    write_capability_plan,
)
from infra_fleet_advisor.runtime.clock import SystemClock
from infra_fleet_advisor.runtime.composition import (
    DEFAULT_SYNTHESIZER,
    SYNTHESIZERS,
    RunInputs,
    compose_and_run,
)
from infra_fleet_advisor.runtime.drill import drills_passed, load_drills, run_drills
from infra_fleet_advisor.runtime.drill import to_markdown as drill_markdown
from infra_fleet_advisor.runtime.fleet_feedback import (
    MAX_FEEDBACK_PR_HISTORY,
    build_feedback_plan,
    decide_feedback_publication,
    read_feedback_plan,
    read_feedback_pull_requests,
    write_feedback_outputs,
)
from infra_fleet_advisor.runtime.github_issues import GhCliIssueClient, publish_issue_plan
from infra_fleet_advisor.runtime.intent_gate import compare_reports
from infra_fleet_advisor.runtime.intent_gate import to_markdown as gate_markdown
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_REPOSITORY,
    build_issue_plan,
    write_issue_plan,
)
from infra_fleet_advisor.runtime.ratchet import compare_advisors
from infra_fleet_advisor.runtime.ratchet import to_markdown as ratchet_markdown
from infra_fleet_advisor.runtime.report_approval import (
    read_report_approval,
    verify_report_approval,
    write_report_approval,
)
from infra_fleet_advisor.runtime.report_readiness import check_report_readiness
from infra_fleet_advisor.runtime.report_signature import (
    compute_report_signature,
    decide_publication,
    read_declined_pr_body,
    read_latest_declined_pr_body,
)
from infra_fleet_advisor.runtime.report_writer import (
    intent_coverage_summary,
    load_prior_report,
    read_report_source_sha,
    write_report,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.remediation import (
    apply_patches,
    build_patches,
)

EXIT_OK = 0
EXIT_POLICY_ERROR = 2
EXIT_PROVENANCE_ERROR = 3
EXIT_PIPELINE_ERROR = 4
EXIT_UNSAFE_OUTPUT_ERROR = 5
EXIT_INTENT_REGRESSION = 6
EXIT_DRILL_FAILED = 7
EXIT_RATCHET_SLIPPED = 8


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infra-fleet-advisor")
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="Run one fleet_repository_review pass")
    review.add_argument("--checkout", required=True, type=Path)
    review.add_argument("--sha", required=True)
    review.add_argument("--policy", required=True, type=Path)
    review.add_argument("--intent-dir", required=True, type=Path)
    review.add_argument("--output-dir", required=True, type=Path)
    review.add_argument("--prior-report", type=Path, default=None)
    review.add_argument("--source-label", default="infra-fleet-public")
    review.add_argument("--synthesizer", choices=SYNTHESIZERS, default=DEFAULT_SYNTHESIZER)

    gate = sub.add_parser(
        "gate", help="Fail when a fleet change would newly diverge from declared intent"
    )
    gate.add_argument("--base-report", required=True, type=Path)
    gate.add_argument("--head-report", required=True, type=Path)
    gate.add_argument("--summary", type=Path, default=None)
    ratchet = sub.add_parser(
        "ratchet", help="Fail when an advisor change loses proof on an unchanged fleet"
    )
    ratchet.add_argument("--base-report", required=True, type=Path)
    ratchet.add_argument("--head-report", required=True, type=Path)
    ratchet.add_argument("--summary", type=Path, default=None)
    drill = sub.add_parser(
        "drill", help="Apply canary violations to the fleet and confirm each check fires"
    )
    drill.add_argument("--checkout", required=True, type=Path)
    drill.add_argument("--drills", required=True, type=Path)
    drill.add_argument("--policy", required=True, type=Path)
    drill.add_argument("--intent-dir", required=True, type=Path)
    drill.add_argument("--output-dir", required=True, type=Path)
    drill.add_argument("--summary", type=Path, default=None)
    remediate = sub.add_parser(
        "remediate", help="Apply mechanical fixes a published report already justifies"
    )
    remediate.add_argument("--checkout", required=True, type=Path)
    remediate.add_argument("--report", required=True, type=Path)
    remediate.add_argument("--policy", required=True, type=Path)
    remediate.add_argument("--intent-dir", required=True, type=Path)
    remediate.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing"
    )

    signature = sub.add_parser(
        "report-signature", help="Compute the material publication signature of a report"
    )
    signature.add_argument("--report", required=True, type=Path)

    readiness = sub.add_parser(
        "report-readiness", help="Check whether a merged report uses current policy and intent"
    )
    readiness.add_argument("--report", required=True, type=Path)
    readiness.add_argument("--policy", required=True, type=Path)
    readiness.add_argument("--intent-dir", required=True, type=Path)

    publication = sub.add_parser(
        "publication-decision",
        help="Decide whether a report changed or matches an accepted or declined report",
    )
    publication.add_argument("--report", required=True, type=Path)
    publication.add_argument("--prior-report", type=Path, default=None)
    decline_source = publication.add_mutually_exclusive_group()
    decline_source.add_argument("--latest-declined-pr-body", type=Path, default=None)
    decline_source.add_argument("--closed-pr-history", type=Path, default=None)
    publication.add_argument("--repository")
    publication.add_argument("--branch")
    publication.add_argument("--workflow-bot-login", default="github-actions[bot]")

    issues = sub.add_parser(
        "issue-plan", help="Revalidate a merged report and write bounded fleet issue actions"
    )
    issues.add_argument("--report", required=True, type=Path)
    issues.add_argument("--policy", required=True, type=Path)
    issues.add_argument("--intent-dir", required=True, type=Path)
    issues.add_argument("--output", required=True, type=Path)
    issues.add_argument("--approval", type=Path)

    approval = sub.add_parser(
        "report-approval", help="Verify the merged report PR used as the issue decision record"
    )
    approval.add_argument("--pull-request", required=True, type=Path)
    approval.add_argument("--files", required=True, type=Path)
    approval.add_argument("--number", required=True, type=int)
    approval.add_argument("--output", required=True, type=Path)

    publish_issues = sub.add_parser(
        "publish-issues",
        help="Publish a revalidated merged report through the issues-only adapter",
    )
    publish_issues.add_argument("--report", required=True, type=Path)
    publish_issues.add_argument("--policy", required=True, type=Path)
    publish_issues.add_argument("--intent-dir", required=True, type=Path)
    publish_issues.add_argument("--app-bot-login", required=True)
    publish_issues.add_argument("--approval", required=True, type=Path)

    capabilities = sub.add_parser(
        "capability-plan",
        help="Revalidate a merged report and write bounded advisor capability actions",
    )
    capabilities.add_argument("--report", required=True, type=Path)
    capabilities.add_argument("--policy", required=True, type=Path)
    capabilities.add_argument("--intent-dir", required=True, type=Path)
    capabilities.add_argument("--output", required=True, type=Path)

    feedback = sub.add_parser(
        "feedback-plan",
        help="Read closed fleet issue labels and propose accepted policy trade-offs",
    )
    feedback.add_argument("--report", required=True, type=Path)
    feedback.add_argument("--policy", required=True, type=Path)
    feedback.add_argument("--intent-dir", required=True, type=Path)
    feedback.add_argument("--app-bot-login", required=True)
    feedback.add_argument("--output-policy", required=True, type=Path)
    feedback.add_argument("--output-plan", required=True, type=Path)

    feedback_decision = sub.add_parser(
        "feedback-publication-decision",
        help="Choose a safe PR transition for one validated feedback plan",
    )
    feedback_decision.add_argument("--plan", required=True, type=Path)
    feedback_decision.add_argument("--open-prs", required=True, type=Path)
    feedback_decision.add_argument("--history-prs", required=True, type=Path)
    feedback_decision.add_argument("--repository", required=True)
    feedback_decision.add_argument("--branch", required=True)
    feedback_decision.add_argument("--branch-tip")
    feedback_decision.add_argument("--branch-is-recoverable", action="store_true")
    return parser


def _output_dir_is_safe(checkout: Path, output_dir: Path) -> bool:
    """The review is read-only by contract — writing the report inside the
    verified checkout would mutate the target and leave it dirty."""
    checkout_real = checkout.resolve()
    output_real = output_dir.resolve()
    return output_real != checkout_real and not output_real.is_relative_to(checkout_real)


def _remediate(args: argparse.Namespace) -> int:
    """Applies only what a published report already justified. The report is the
    authority on both which concerns are actionable and which files they touch —
    nothing is discovered by scanning the fleet here."""
    plan = build_issue_plan(args.report, args.policy, args.intent_dir)
    eligible = {action.fingerprint for action in plan.actions if action.action == "active"}
    prior = load_prior_report(args.report)
    if prior is None:
        print("no report to act on", file=sys.stderr)
        return EXIT_POLICY_ERROR

    # The evidence describes one commit. If the checkout has moved on, those
    # line numbers and paths describe a tree nobody analyzed or accepted, so
    # refuse rather than patch blind. Also rejects a dirty checkout.
    verify_snapshot(args.checkout, read_report_source_sha(args.report), "infra-fleet-public")

    applied: list[str] = []
    for rec in prior.recommendations:
        # A suppressed concern is one the owner deliberately excluded; a
        # resolved one is already fixed, and an accepted trade-off is a choice
        # to live with the finding. None justifies touching the fleet.
        if rec.fingerprint not in eligible:
            continue
        patches = build_patches(
            checkout_root=args.checkout,
            concern_key=rec.concern_key,
            evidence_ids=rec.evidence_ids,
            evidence_by_id=prior.evidence_by_id,
        )
        if not patches:
            continue
        if not args.dry_run:
            apply_patches(args.checkout, patches)
        applied += [f"{rec.concern_key}: {p.path} — {p.summary}" for p in patches]

    if not applied:
        print("no mechanically fixable findings in this report")
        return EXIT_OK
    verb = "would change" if args.dry_run else "changed"
    print(f"{verb} {len(applied)} file(s):")
    for line in applied:
        print(f"  {line}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "gate":
        try:
            gate_result = compare_reports(args.base_report, args.head_report)
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        summary = gate_markdown(gate_result)
        print(summary)
        if args.summary is not None:
            with args.summary.open("a", encoding="utf-8") as handle:
                handle.write(summary)
        return EXIT_OK if gate_result.passed else EXIT_INTENT_REGRESSION

    if args.command == "ratchet":
        try:
            ratchet_result = compare_advisors(args.base_report, args.head_report)
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        ratchet_summary = ratchet_markdown(ratchet_result)
        print(ratchet_summary)
        if args.summary is not None:
            with args.summary.open("a", encoding="utf-8") as handle:
                handle.write(ratchet_summary)
        return EXIT_OK if ratchet_result.passed else EXIT_RATCHET_SLIPPED

    if args.command == "drill":

        def review_once(worktree: Path, sha: str, output_dir: Path) -> None:
            code = main(
                [
                    "review",
                    "--checkout",
                    str(worktree),
                    "--sha",
                    sha,
                    "--policy",
                    str(args.policy),
                    "--intent-dir",
                    str(args.intent_dir),
                    "--output-dir",
                    str(output_dir),
                    "--synthesizer",
                    "stub",
                ]
            )
            if code != EXIT_OK:
                raise PolicyError(f"review of a drill commit failed with exit code {code}")

        checkout_real = args.checkout.resolve()
        destinations = [args.output_dir] + ([args.summary] if args.summary else [])
        if any(
            path.resolve() == checkout_real or path.resolve().is_relative_to(checkout_real)
            for path in destinations
        ):
            print("drill error: output must be outside the fleet checkout", file=sys.stderr)
            return EXIT_UNSAFE_OUTPUT_ERROR
        try:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            drill_results = run_drills(
                args.checkout.resolve(),
                load_drills(args.drills),
                review_once,
                args.output_dir.resolve(),
            )
        except PolicyError as exc:
            print(f"drill error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except subprocess.CalledProcessError as exc:
            # The command line names machine paths; report only what failed.
            print(
                f"drill error: git {exc.cmd[5] if len(exc.cmd) > 5 else ''} failed", file=sys.stderr
            )
            return EXIT_PIPELINE_ERROR
        except OSError as exc:
            print(f"drill error: {type(exc).__name__} while preparing a drill", file=sys.stderr)
            return EXIT_PIPELINE_ERROR
        drill_summary = drill_markdown(drill_results)
        print(drill_summary)
        if args.summary is not None:
            with args.summary.open("a", encoding="utf-8") as handle:
                handle.write(drill_summary)
        return EXIT_OK if drills_passed(drill_results) else EXIT_DRILL_FAILED

    if args.command == "report-readiness":
        try:
            readiness = check_report_readiness(args.report, args.policy, args.intent_dir)
            print(json.dumps(asdict(readiness), sort_keys=True))
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR

    if args.command == "report-approval":
        try:
            report_approval = verify_report_approval(args.pull_request, args.files, args.number)
            write_report_approval(report_approval, args.output)
            print(json.dumps(asdict(report_approval), sort_keys=True))
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except OSError as exc:
            print(
                f"pipeline error: cannot write report approval: {type(exc).__name__}",
                file=sys.stderr,
            )
            return EXIT_PIPELINE_ERROR

    if args.command == "capability-plan":
        try:
            capability_plan = build_capability_plan(args.report, args.policy, args.intent_dir)
            write_capability_plan(capability_plan, args.output)
            active = sum(action.action == "active" for action in capability_plan.actions)
            print(
                f"wrote capability plan with {active} active gap(s) and "
                f"{len(capability_plan.actions) - active} resolution action(s)"
            )
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except OSError as exc:
            print(
                f"pipeline error: cannot write capability plan: {type(exc).__name__}",
                file=sys.stderr,
            )
            return EXIT_PIPELINE_ERROR

    if args.command == "feedback-publication-decision":
        try:
            feedback_plan = read_feedback_plan(args.plan)
            open_prs = read_feedback_pull_requests(
                args.open_prs,
                repository=args.repository,
                branch=args.branch,
                maximum=1,
            )
            history_prs = read_feedback_pull_requests(
                args.history_prs,
                repository=args.repository,
                branch=args.branch,
                maximum=MAX_FEEDBACK_PR_HISTORY,
            )
            feedback_decision = decide_feedback_publication(
                feedback_plan,
                open_prs,
                history_prs,
                branch_tip=args.branch_tip,
                branch_is_recoverable=args.branch_is_recoverable,
            )
            print(json.dumps(asdict(feedback_decision), sort_keys=True))
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR

    if args.command == "feedback-plan":
        try:
            client = GhCliIssueClient(FLEET_REPOSITORY)
            feedback_plan = build_feedback_plan(
                args.report,
                args.policy,
                client.all_advisor_issue_records(),
                args.app_bot_login,
                args.intent_dir,
            )
            write_feedback_outputs(
                feedback_plan,
                args.policy,
                args.output_policy,
                args.output_plan,
            )
            print(
                f"wrote {feedback_plan.status} feedback plan with "
                f"{len(feedback_plan.additions)} policy addition(s)"
            )
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except AdvisorError as exc:
            print(f"pipeline error: {exc}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR
        except OSError as exc:
            print(f"pipeline error: cannot write feedback: {type(exc).__name__}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    if args.command == "publish-issues":
        try:
            issue_plan = build_issue_plan(
                args.report,
                args.policy,
                args.intent_dir,
                approval=read_report_approval(args.approval),
            )
            result = publish_issue_plan(
                issue_plan,
                GhCliIssueClient(issue_plan.target_repository),
                args.app_bot_login,
            )
            print(
                f"published {result.created} issue(s), found {result.existing} existing, "
                f"restored {result.labels_restored} label set(s), and added "
                f"{result.resolution_comments} resolution note(s); "
                f"deferred {issue_plan.deferred_count} recommendation(s) with incomplete coverage"
            )
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except AdvisorError as exc:
            print(f"pipeline error: {exc}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    if args.command == "issue-plan":
        try:
            issue_plan = build_issue_plan(
                args.report,
                args.policy,
                args.intent_dir,
                approval=read_report_approval(args.approval) if args.approval else None,
            )
            write_issue_plan(issue_plan, args.output)
            print(
                f"wrote issue plan with {len(issue_plan.actions)} action(s); "
                f"deferred {issue_plan.deferred_count} recommendation(s) with incomplete coverage"
            )
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except OSError as exc:
            print(f"pipeline error: cannot write issue plan: {type(exc).__name__}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    if args.command == "publication-decision":
        try:
            if args.closed_pr_history is not None:
                if args.repository is None or args.branch is None:
                    raise PolicyError(
                        "--repository and --branch are required with --closed-pr-history"
                    )
                declined_body = read_latest_declined_pr_body(
                    args.closed_pr_history,
                    repository=args.repository,
                    branch=args.branch,
                    workflow_bot_login=args.workflow_bot_login,
                )
            else:
                if (
                    args.repository is not None
                    or args.branch is not None
                    or args.workflow_bot_login != "github-actions[bot]"
                ):
                    raise PolicyError("--repository and --branch require --closed-pr-history")
                declined_body = (
                    read_declined_pr_body(args.latest_declined_pr_body)
                    if args.latest_declined_pr_body is not None
                    else ""
                )
            publication_decision = decide_publication(
                args.report,
                prior_report=args.prior_report,
                latest_declined_pr_body=declined_body,
            )
            print(json.dumps(asdict(publication_decision), sort_keys=True))
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR

    if args.command == "report-signature":
        try:
            print(compute_report_signature(args.report))
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR

    if args.command == "remediate":
        try:
            return _remediate(args)
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except ProvenanceError as exc:
            print(f"provenance error: {exc}", file=sys.stderr)
            return EXIT_PROVENANCE_ERROR
        except AdvisorError as exc:
            print(f"pipeline error: {exc}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    if not _output_dir_is_safe(args.checkout, args.output_dir):
        print(
            f"unsafe output error: --output-dir ({args.output_dir}) must not be "
            f"inside --checkout ({args.checkout})",
            file=sys.stderr,
        )
        return EXIT_UNSAFE_OUTPUT_ERROR

    inputs = RunInputs(
        checkout=args.checkout,
        expected_sha=args.sha,
        policy_path=args.policy,
        source_label=args.source_label,
        prior_report_path=args.prior_report,
        synthesizer_name=args.synthesizer,
        intent_dir=args.intent_dir,
    )
    try:
        report = compose_and_run(inputs, SystemClock())
    except PolicyError as exc:
        print(f"policy error: {exc}", file=sys.stderr)
        return EXIT_POLICY_ERROR
    except ProvenanceError as exc:
        print(f"provenance error: {exc}", file=sys.stderr)
        return EXIT_PROVENANCE_ERROR
    except AdvisorError as exc:
        print(f"pipeline error: {exc}", file=sys.stderr)
        return EXIT_PIPELINE_ERROR

    json_path, md_path = write_report(report, args.output_dir)
    print(
        f"wrote {json_path} and {md_path} — "
        f"{report.new_count} new, {report.unchanged_count} unchanged, "
        f"{report.resolved_count} resolved, {report.suppressed_count} suppressed"
    )
    coverage_summary = intent_coverage_summary(report)
    if coverage_summary is not None:
        print(f"Intent: {coverage_summary}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
