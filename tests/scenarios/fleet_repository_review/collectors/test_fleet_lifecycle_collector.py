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


ONBOARDING = (
    "mode=${1:-plan}\n"
    'echo "AWS target: $arn"\n'
    'echo "GitHub target: $GITHUB_REPOSITORY"\n'
    'printf \'%s\' "$value" | gh secret set "$name" --repo "$GITHUB_REPOSITORY"\n'
    "echo 'Next: ./fleet up --profile aws-staging'\n"
)


def _write_contract(
    root: Path,
    *,
    facade_actions: str = "setup|up|down|status",
    local_actions: tuple[str, ...] = ("setup", "up", "down"),
    aws_actions: tuple[str, ...] = ("setup", "up", "down"),
    local_first_use: bool = True,
    aws_onboarding: str = ONBOARDING,
    aws_teardown: str = 'aws_dispatch nightly-destroy.yml --field "confirm_destroy=$typed"',
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
        first_use = ""
        if name == "local" and local_first_use:
            first_use = (
                'kctl() { kubectl --kubeconfig "$FLEET_STATE/kubeconfig" '
                '--context "$FLEET_CONTEXT" "$@"; }\n'
                'fctl() { flux --kubeconfig "$FLEET_STATE/kubeconfig" '
                '--context "$FLEET_CONTEXT" "$@"; }\n'
                "local_init_state() {\n"
                "  common_dir=$(git rev-parse --path-format=absolute --git-common-dir)\n"
                '  FLEET_STATE="$common_dir/fleet/local"\n'
                "}\n"
                "local_setup() {\n"
                '  "$fleet_root/scripts/install-profile-tools.sh" '
                '"$FLEET_STATE/bin" --local\n'
                '  export PATH="$FLEET_STATE/bin:$PATH"\n'
                "  echo 'Next: ./fleet up --profile local'\n"
                "}\n"
                "local_prerequisites() {\n"
                '  export PATH="$FLEET_STATE/bin:$PATH"\n'
                "}\n"
            )
        if name == "aws-staging":
            first_use = (
                'setup_plan() {\n  exec "$fleet_root/scripts/onboard-aws-profile.sh" plan ;;\n}\n'
                f"aws_down() {{\n  {aws_teardown}\n}}\n"
            )
        (strategies / f"{name}.sh").write_text(
            first_use + f'profile_main() {{\n  case "$1" in\n{cases}\n  esac\n}}\n',
            encoding="utf-8",
        )
    (root / "scripts" / "onboard-aws-profile.sh").write_text(aws_onboarding, encoding="utf-8")


def _record(result: collector.CollectorResult, source_path: str) -> collector.Evidence:
    [evidence] = [item for item in result.evidence if item.source_path == source_path]
    return evidence


def _local(result: collector.CollectorResult) -> collector.Evidence:
    return _record(result, "scripts/fleet-profiles/local.sh")


def _aws(result: collector.CollectorResult) -> collector.Evidence:
    return _record(result, "scripts/fleet-profiles/aws-staging.sh")


def test_each_check_has_its_own_evidence_identity(tmp_path: Path) -> None:
    _write_contract(tmp_path)

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.evidence_count == 3
    assert len({item.evidence_id for item in result.evidence}) == 3
    assert {item.source_path for item in result.evidence} == {
        "fleet",
        "scripts/fleet-profiles/local.sh",
        "scripts/fleet-profiles/aws-staging.sh",
    }


def test_complete_lifecycle_surface_emits_bounded_typed_evidence(tmp_path: Path) -> None:
    _write_contract(tmp_path)

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "ok"
    evidence = _record(result, "fleet")
    assert evidence.kind == EVIDENCE_KIND_FLEET_LIFECYCLE
    assert evidence.fact["common_lifecycle_complete"] is True
    assert evidence.fact["local_lifecycle_complete"] is True
    assert evidence.fact["aws_lifecycle_complete"] is True
    local = _local(result)
    assert local.fact["local_first_use_complete"] is True
    assert local.fact["local_installs_pinned_tools"] is True
    assert local.fact["local_uses_checkout_state"] is True
    assert local.fact["local_uses_explicit_context"] is True
    assert local.fact["local_prints_next_command"] is True
    assert _aws(result).fact["aws_onboarding_complete"] is True


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


def test_missing_local_first_use_controls_is_a_distinct_divergence(tmp_path: Path) -> None:
    _write_contract(tmp_path, local_first_use=False)

    result = collector.collect(tmp_path, LIMITS)

    assert _record(result, "fleet").fact["common_lifecycle_complete"] is True
    evidence = _local(result)
    assert evidence.fact["local_first_use_complete"] is False
    assert evidence.fact["local_installs_pinned_tools"] is False
    assert "local first-use: false" in evidence.excerpt


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


def test_each_missing_aws_onboarding_control_is_divergent(tmp_path: Path) -> None:
    weakened = {
        "aws_setup_plans_by_default": {"aws_onboarding": ONBOARDING.replace(":-plan", ":---apply")},
        "aws_setup_reports_targets": {"aws_onboarding": ONBOARDING.replace("GitHub target", "Hi")},
        "aws_secrets_from_stdin": {
            "aws_onboarding": ONBOARDING.replace('--repo "', '--body "$value" --repo "')
        },
        "aws_prints_next_command": {"aws_onboarding": ONBOARDING.replace("Next:", "Then")},
        "aws_teardown_operator_confirmed": {
            "aws_teardown": (
                "aws_dispatch nightly-destroy.yml --field 'confirm_destroy=destroy staging'"
            )
        },
    }
    for index, (fact, overrides) in enumerate(weakened.items()):
        root = tmp_path / str(index)
        root.mkdir()
        _write_contract(root, **overrides)

        result = collector.collect(root, LIMITS)

        evidence = _aws(result)
        assert evidence.fact[fact] is False, fact
        assert evidence.fact["aws_onboarding_complete"] is False
        assert _record(result, "fleet").fact["common_lifecycle_complete"] is True


def test_missing_onboarding_coordinator_is_divergent_not_partial(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    (tmp_path / "scripts" / "onboard-aws-profile.sh").unlink()

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "ok"
    assert _aws(result).fact["aws_onboarding_complete"] is False
