import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from infra_fleet_advisor.core.errors import AdvisorError, PolicyError, ProvenanceError
from infra_fleet_advisor.runtime.clock import SystemClock
from infra_fleet_advisor.runtime.composition import SYNTHESIZERS, RunInputs, compose_and_run
from infra_fleet_advisor.runtime.report_writer import load_prior_report, write_report
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

    applied: list[str] = []
    for rec in prior.recommendations:
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

    if args.command == "remediate":
        try:
            return _remediate(args)
        except PolicyError as exc:
            print(f"policy error: {exc}", file=sys.stderr)
            return EXIT_POLICY_ERROR
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
