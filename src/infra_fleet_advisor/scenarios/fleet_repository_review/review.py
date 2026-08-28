import time
from pathlib import Path

from infra_fleet_advisor import ADVISOR_VERSION
from infra_fleet_advisor.config.policy import AdvisorPolicy
from infra_fleet_advisor.core.errors import BoundedExecutionExceeded
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.lifecycle import PriorReport
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import (
    CollectorCoverage,
    Report,
    RunProvenance,
    assemble_report,
)
from infra_fleet_advisor.provenance.source_verification import SourceProvenance, list_tracked_paths
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    github_actions_workflow_collector as gha_collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    terraform_iam_collector as tf_iam_collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import CONCERN_RULES
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    GHA_COLLECTOR_ID,
    GHA_COLLECTOR_VERSION,
    TF_IAM_COLLECTOR_ID,
    TF_IAM_COLLECTOR_VERSION,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import (
    EvidenceProjection,
    PolicyContext,
    Synthesizer,
)


def check_wall_clock_budget(elapsed_seconds: float, limits: ExecutionLimits) -> None:
    if elapsed_seconds > limits.max_wall_seconds:
        raise BoundedExecutionExceeded(
            f"review exceeded max_wall_seconds ({limits.max_wall_seconds}s): "
            f"took {elapsed_seconds:.1f}s"
        )


def check_model_call_budget(call_count: int, limits: ExecutionLimits) -> None:
    if call_count > limits.max_model_calls:
        raise BoundedExecutionExceeded(
            f"review exceeded max_model_calls ({limits.max_model_calls}): made {call_count}"
        )


def run_review(
    *,
    checkout_root: Path,
    policy: AdvisorPolicy,
    source: SourceProvenance,
    synthesizer: Synthesizer,
    limits: ExecutionLimits,
    prior: PriorReport | None,
    run_started_at: str,
) -> Report:
    """The one vertical scenario: select collectors, project evidence for
    synthesis, and run the bounded core pipeline. No recommendation
    semantics live here — that's core's job."""
    started = time.monotonic()
    excluded_paths = frozenset(policy.evidence_path_exclusions)

    gha_result = gha_collector.collect(
        checkout_root,
        limits,
        excluded_paths=excluded_paths,
        tracked_paths=list_tracked_paths(checkout_root, ".github/workflows"),
    )
    tf_result = tf_iam_collector.collect(
        checkout_root,
        limits,
        excluded_paths=excluded_paths,
        tracked_paths=list_tracked_paths(checkout_root, "infrastructure"),
    )
    all_evidence: tuple[Evidence, ...] = gha_result.evidence + tf_result.evidence
    evidence_by_id = {e.evidence_id: e for e in all_evidence}
    coverage: list[CollectorCoverage] = [gha_result.coverage, tf_result.coverage]

    projection = EvidenceProjection(
        policy_context=PolicyContext(
            enabled_categories=policy.enabled_categories,
            max_recommendations=policy.max_recommendations,
        ),
        evidence=all_evidence,
    )
    synthesis_response = synthesizer.synthesize(projection)
    check_model_call_budget(call_count=1, limits=limits)
    check_wall_clock_budget(time.monotonic() - started, limits)

    provenance = RunProvenance(
        source_commit_sha=source.commit_sha,
        source_label=source.source_label,
        advisor_version=ADVISOR_VERSION,
        policy_version=policy.version,
        collector_versions={
            GHA_COLLECTOR_ID: GHA_COLLECTOR_VERSION,
            TF_IAM_COLLECTOR_ID: TF_IAM_COLLECTOR_VERSION,
        },
        model_identifier=synthesis_response.model_identifier,
        run_started_at=run_started_at,
    )

    report, _rejected = assemble_report(
        provenance=provenance,
        coverage=coverage,
        candidates=synthesis_response.recommendations,
        evidence_by_id=evidence_by_id,
        bounds=policy.to_bounds(),
        concern_rules=CONCERN_RULES,
        prior=prior,
    )
    return report
