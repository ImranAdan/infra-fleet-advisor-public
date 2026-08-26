import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from infra_fleet_advisor.core.errors import AdvisorError, PolicyError, ProvenanceError
from infra_fleet_advisor.runtime.clock import SystemClock
from infra_fleet_advisor.runtime.composition import RunInputs, compose_and_run
from infra_fleet_advisor.runtime.report_writer import write_report

EXIT_OK = 0
EXIT_POLICY_ERROR = 2
EXIT_PROVENANCE_ERROR = 3
EXIT_PIPELINE_ERROR = 4


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    inputs = RunInputs(
        checkout=args.checkout,
        expected_sha=args.sha,
        policy_path=args.policy,
        source_label=args.source_label,
        prior_report_path=args.prior_report,
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
