from dataclasses import replace
from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    kubernetes_deployment_collector as collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def test_single_replica_defaults_preserve_capacity(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_default_single.yaml",))

    result = collector.collect(repo, LIMITS)

    assert result.coverage.status == "ok"
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.kind == EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY
    assert evidence.fact["effective_max_unavailable"] == 0
    assert evidence.fact["effective_max_surge"] == 1
    assert evidence.fact["retains_healthy_capacity"] is True


def test_explicit_zero_unavailable_preserves_multi_replica_capacity(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_explicit_safe.yaml",))

    evidence = collector.collect(repo, LIMITS).evidence[0]

    assert evidence.fact["replicas"] == 4
    assert evidence.fact["retains_healthy_capacity"] is True


def test_default_fenceposts_can_reduce_multi_replica_capacity(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_default_unsafe.yaml",))

    evidence = collector.collect(repo, LIMITS).evidence[0]

    assert evidence.fact["effective_max_unavailable"] == 1
    assert evidence.fact["retains_healthy_capacity"] is False


def test_missing_readiness_probe_is_not_treated_as_healthy_capacity(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_without_readiness.yaml",))

    evidence = collector.collect(repo, LIMITS).evidence[0]

    assert evidence.fact["all_containers_have_readiness_probe"] is False
    assert evidence.fact["retains_healthy_capacity"] is False


def test_recreate_strategy_cannot_preserve_active_capacity(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_recreate.yaml",))

    evidence = collector.collect(repo, LIMITS).evidence[0]

    assert evidence.fact["strategy_type"] == "Recreate"
    assert evidence.fact["retains_healthy_capacity"] is False


def test_malformed_manifest_makes_coverage_partial_without_hiding_good_evidence(
    git_checkout,
) -> None:
    repo, _sha = git_checkout(kubernetes_files=("malformed.yaml", "rollout_default_single.yaml"))

    result = collector.collect(repo, LIMITS)

    assert result.coverage.status == "partial"
    assert result.coverage.error_summary is not None
    assert len(result.evidence) == 1


def test_duplicate_resource_identity_is_unverified_not_arbitrarily_selected(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_default_single.yaml",))
    source = repo / "k8s" / "applications" / "rollout_default_single.yaml"
    duplicate = source.with_name("duplicate.yaml")
    duplicate.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    result = collector.collect(repo, LIMITS)

    assert result.coverage.status == "partial"
    assert result.evidence == ()


def test_resource_identity_survives_a_manifest_rename(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_default_single.yaml",))
    before = collector.collect(repo, LIMITS).evidence[0]
    source = repo / "k8s" / "applications" / "rollout_default_single.yaml"
    source.rename(source.with_name("renamed.yaml"))

    after = collector.collect(repo, LIMITS).evidence[0]

    assert before.source_path != after.source_path
    assert before.evidence_id == after.evidence_id


def test_k8s_directory_escaping_checkout_is_failed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "k8s").symlink_to(outside)

    result = collector.collect(checkout, LIMITS)

    assert result.coverage.status == "failed"
    assert result.evidence == ()


def test_untracked_manifest_is_not_evidence(git_checkout) -> None:
    repo, _sha = git_checkout(kubernetes_files=("rollout_default_unsafe.yaml",))

    result = collector.collect(repo, LIMITS, tracked_paths=frozenset())

    assert result.coverage.status == "partial"
    assert result.evidence == ()
    assert "not part of the verified commit" in (result.coverage.error_summary or "")


def test_manifest_file_limit_is_explicitly_partial(git_checkout) -> None:
    repo, _sha = git_checkout(
        kubernetes_files=("rollout_default_single.yaml", "rollout_explicit_safe.yaml")
    )

    result = collector.collect(repo, replace(LIMITS, max_manifest_files=1))

    assert result.coverage.status == "partial"
    assert len(result.evidence) == 1
    assert "omitted by safety limit" in (result.coverage.error_summary or "")
