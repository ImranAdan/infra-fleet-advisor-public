import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from infra_fleet_advisor.core.errors import AdvisorError, PolicyError, ProvenanceError
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.runtime.clock import SystemClock
from infra_fleet_advisor.runtime.composition import SYNTHESIZERS, RunInputs, compose_and_run
from infra_fleet_advisor.runtime.fleet_feedback import (
    build_feedback_plan,
    decide_feedback_publication,
    read_feedback_plan,
    read_feedback_pull_requests,
    write_feedback_outputs,
)
from infra_fleet_advisor.runtime.github_issues import GhCliIssueClient, publish_issue_plan
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_REPOSITORY,
    build_issue_plan,
    write_issue_plan,
)
from infra_fleet_advisor.runtime.report_signature import (
    compute_report_signature,
    decide_publication,
    read_declined_pr_body,
)
from infra_fleet_advisor.runtime.report_writer import (
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infra-fleet-advisor")
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review", help="Run one fleet_repository_review pass")
    review.add_argument("--checkout", required=True, type=Path)
    review.add_argument("--sha", required=True)
    review.add_argument("--policy", required=True, type=Path)
    review.add_argument("--output-dir", required=True, type=Path)
    review.add_argument("--prior-report", type=Path, default=None)
    review.add_argument("--source-label", default="infra-fleet-public")
    review.add_argument("--synthesizer", choices=SYNTHESIZERS, default=SYNTHESIZERS[0])

    remediate = sub.add_parser(
        "remediate", help="Apply mechanical fixes a published report already justifies"
    )
    remediate.add_argument("--checkout", required=True, type=Path)
    remediate.add_argument("--report", required=True, type=Path)
    remediate.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing"
    )

    signature = sub.add_parser(
        "report-signature", help="Compute the material publication signature of a report"
    )
    signature.add_argument("--report", required=True, type=Path)

    publication = sub.add_parser(
        "publication-decision",
        help="Decide whether a report changed or matches an accepted or declined report",
    )
    publication.add_argument("--report", required=True, type=Path)
    publication.add_argument("--prior-report", type=Path, default=None)
    publication.add_argument("--latest-declined-pr-body", type=Path, default=None)

    issues = sub.add_parser(
        "issue-plan", help="Revalidate a merged report and write bounded fleet issue actions"
    )
    issues.add_argument("--report", required=True, type=Path)
    issues.add_argument("--policy", required=True, type=Path)
    issues.add_argument("--output", required=True, type=Path)

    publish_issues = sub.add_parser(
        "publish-issues",
        help="Publish a revalidated merged report through the issues-only adapter",
    )
    publish_issues.add_argument("--report", required=True, type=Path)
    publish_issues.add_argument("--policy", required=True, type=Path)
    publish_issues.add_argument("--app-bot-login", required=True)

    feedback = sub.add_parser(
        "feedback-plan",
        help="Read closed fleet issue labels and propose accepted policy trade-offs",
    )
    feedback.add_argument("--report", required=True, type=Path)
    feedback.add_argument("--policy", required=True, type=Path)
    feedback.add_argument("--app-bot-login", required=True)
    feedback.add_argument("--output-policy", required=True, type=Path)
    feedback.add_argument("--output-plan", required=True, type=Path)

    feedback_decision = sub.add_parser(
        "feedback-publication-decision",
        help="Choose a safe PR transition for one validated feedback plan",
    )
    feedback_decision.add_argument("--plan", required=True, type=Path)
    feedback_decision.add_argument("--open-prs", required=True, type=Path)
    feedback_decision.add_argument("--latest-prs", required=True, type=Path)
    feedback_decision.add_argument("--repository", required=True)
    feedback_decision.add_argument("--branch", required=True)
    feedback_decision.add_argument("--branch-tip")
    feedback_decision.add_argument("--branch-matches-plan", action="store_true")
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
        if rec.status not in ("new", "unchanged") or rec.owner_accepted_trade_off:
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

    if args.command == "feedback-publication-decision":
        try:
            feedback_plan = read_feedback_plan(args.plan)
            open_prs = read_feedback_pull_requests(
                args.open_prs,
                repository=args.repository,
                branch=args.branch,
                maximum=1,
            )
            latest_prs = read_feedback_pull_requests(
                args.latest_prs,
                repository=args.repository,
                branch=args.branch,
                maximum=1,
            )
            feedback_decision = decide_feedback_publication(
                feedback_plan,
                open_prs,
                latest_prs,
                branch_tip=args.branch_tip,
                branch_matches_plan=args.branch_matches_plan,
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
            issue_plan = build_issue_plan(args.report, args.policy)
            result = publish_issue_plan(
                issue_plan,
                GhCliIssueClient(issue_plan.target_repository),
                args.app_bot_login,
            )
            print(
                f"published {result.created} issue(s), found {result.existing} existing, "
                f"restored {result.labels_restored} label set(s), and added "
                f"{result.resolution_comments} resolution note(s)"
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
            issue_plan = build_issue_plan(args.report, args.policy)
            write_issue_plan(issue_plan, args.output)
            print(f"wrote issue plan with {len(issue_plan.actions)} action(s)")
            return EXIT_OK
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
        except OSError as exc:
            print(f"pipeline error: cannot write issue plan: {type(exc).__name__}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR

    if args.command == "publication-decision":
        try:
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
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
