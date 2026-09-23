from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    fleet_lifecycle_collector as collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_FLEET_LIFECYCLE,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def _write_contract(
    root: Path,
    *,
    facade_actions: str = "setup|up|down|status",
    local_actions: tuple[str, ...] = ("setup", "up", "down"),
    aws_actions: tuple[str, ...] = ("setup", "up", "down"),
) -> None:
    facade = root / "fleet"
    facade.write_text(
        (
            "#!/usr/bin/env bash\n"
            'action=${1:-help}\nprofile=""\n'
            "case \"$profile\" in local|aws-staging) ;; *) echo 'Choose --profile' ;; esac\n"
            f'case "$action" in {facade_actions}) ;; *) echo "Unknown action: $action" ;; esac\n'
            'case "$profile" in\n'
            '  local) source "$fleet_root/scripts/fleet-profiles/local.sh" ;;\n'
            '  aws-staging) source "$fleet_root/scripts/fleet-profiles/aws-staging.sh" ;;\n'
            "esac\n"
            'profile_main "$action" "$revision" "$service" "$apply"\n'
        ),
        encoding="utf-8",
    )
    facade.chmod(0o755)
    strategies = root / "scripts" / "fleet-profiles"
    strategies.mkdir(parents=True)
    for name, actions in (("local", local_actions), ("aws-staging", aws_actions)):
        cases = "\n".join(f"    {action}) command ;;" for action in actions)
        (strategies / f"{name}.sh").write_text(
            f'profile_main() {{\n  case "$1" in\n{cases}\n  esac\n}}\n',
            encoding="utf-8",
        )


def test_complete_lifecycle_surface_emits_bounded_typed_evidence(tmp_path: Path) -> None:
    _write_contract(tmp_path)

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "ok"
    assert result.coverage.evidence_count == 1
    evidence = result.evidence[0]
    assert evidence.kind == EVIDENCE_KIND_FLEET_LIFECYCLE
    assert evidence.source_path == "fleet"
    assert evidence.fact["common_lifecycle_complete"] is True
    assert evidence.fact["local_lifecycle_complete"] is True
    assert evidence.fact["aws_lifecycle_complete"] is True


def test_missing_setup_is_a_stable_actionable_divergence(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        facade_actions="up|down|status",
        local_actions=("up", "down"),
        aws_actions=("up", "down"),
    )

    first = collector.collect(tmp_path, LIMITS).evidence[0]
    (tmp_path / "fleet").write_text(
        (tmp_path / "fleet").read_text(encoding="utf-8") + "# unrelated comment\n",
        encoding="utf-8",
    )
    second = collector.collect(tmp_path, LIMITS).evidence[0]

    assert first.evidence_id == second.evidence_id
    assert first.fact["common_lifecycle_complete"] is False
    assert first.fact["facade_lifecycle_complete"] is False
    assert first.fact["local_lifecycle_complete"] is False
    assert first.fact["aws_lifecycle_complete"] is False
    assert "false/false/false" in first.excerpt


def test_profile_without_all_lifecycle_routes_is_divergent(tmp_path: Path) -> None:
    _write_contract(tmp_path, aws_actions=("setup", "up"))

    evidence = collector.collect(tmp_path, LIMITS).evidence[0]

    assert evidence.fact["facade_lifecycle_complete"] is True
    assert evidence.fact["local_lifecycle_complete"] is True
    assert evidence.fact["aws_lifecycle_complete"] is False
    assert evidence.fact["common_lifecycle_complete"] is False


def test_unknown_shell_structure_is_partial_instead_of_a_false_finding(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    facade = tmp_path / "fleet"
    facade.write_text('#!/usr/bin/env bash\nexec dynamic-dispatch "$@"\n', encoding="utf-8")
    facade.chmod(0o755)

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"
    assert result.evidence == ()
    assert "could not be parsed" in (result.coverage.error_summary or "")


def test_profile_strategy_mapping_must_be_exact(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    facade = tmp_path / "fleet"
    facade.write_text(
        facade.read_text(encoding="utf-8").replace(
            "scripts/fleet-profiles/aws-staging.sh", "scripts/fleet-profiles/local.sh"
        ),
        encoding="utf-8",
    )

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"
    assert result.evidence == ()
    assert "outside the registered" in (result.coverage.error_summary or "")


def test_new_profile_requires_a_collector_update_instead_of_a_false_finding(
    tmp_path: Path,
) -> None:
    _write_contract(tmp_path)
    facade = tmp_path / "fleet"
    facade.write_text(
        facade.read_text(encoding="utf-8").replace(
            "local|aws-staging)", "local|aws-staging|new-profile)"
        ),
        encoding="utf-8",
    )

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"
    assert result.evidence == ()
    assert "outside the registered" in (result.coverage.error_summary or "")


def test_untracked_or_excluded_source_cannot_be_evidence(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    local_path = "scripts/fleet-profiles/local.sh"
    aws_path = "scripts/fleet-profiles/aws-staging.sh"

    untracked = collector.collect(tmp_path, LIMITS, tracked_paths=frozenset({"fleet"}))
    excluded = collector.collect(
        tmp_path,
        LIMITS,
        excluded_paths=frozenset({local_path}),
        tracked_paths=frozenset({"fleet", local_path, aws_path}),
    )

    assert untracked.coverage.status == "partial"
    assert untracked.evidence == ()
    assert "not part of the verified commit" in (untracked.coverage.error_summary or "")
    assert excluded.coverage.status == "partial"
    assert excluded.evidence == ()


def test_missing_facade_leaves_the_intent_unverified(tmp_path: Path) -> None:
    result = collector.collect(tmp_path, LIMITS, tracked_paths=frozenset())

    assert result.coverage.status == "ok"
    assert result.evidence == ()
