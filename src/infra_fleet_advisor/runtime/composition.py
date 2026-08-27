from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import Report
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.runtime.clock import Clock
from infra_fleet_advisor.runtime.report_writer import load_prior_report
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.review import run_review
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import (
    StubSynthesizer,
    Synthesizer,
)

MAX_WORKFLOW_FILES = 50
MAX_WORKFLOW_FILE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class RunInputs:
    checkout: Path
    expected_sha: str
    policy_path: Path
    source_label: str
    prior_report_path: Path | None


def compose_and_run(
    inputs: RunInputs, clock: Clock, synthesizer: Synthesizer | None = None
) -> Report:
    """Wires one invocation: verify checkout, load policy, load prior report,
    run the scenario. The only place a real model client would be wired in."""
    policy = load_policy(inputs.policy_path, TAXONOMY)
    source = verify_snapshot(inputs.checkout, inputs.expected_sha, inputs.source_label)
    prior = load_prior_report(inputs.prior_report_path)
    limits = ExecutionLimits(
        max_wall_seconds=policy.max_wall_seconds,
        max_model_calls=policy.max_model_calls,
        max_workflow_files=MAX_WORKFLOW_FILES,
        max_file_bytes=MAX_WORKFLOW_FILE_BYTES,
        max_recommendations=policy.max_recommendations,
    )
    return run_review(
        checkout_root=inputs.checkout,
        policy=policy,
        source=source,
        synthesizer=synthesizer or StubSynthesizer(),
        limits=limits,
        prior=prior,
        run_started_at=clock.now_iso(),
    )
