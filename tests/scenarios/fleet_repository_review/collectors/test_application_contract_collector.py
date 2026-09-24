from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    application_contract_collector as collector,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def _contract(name: str) -> str:
    return (
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: fleet-app, namespace: flux-system}\n"
        f"data: {{APP_NAME: {name}, APP_PORT: '80'}}\n"
    )


def _fleet(tmp_path: Path, extra: dict[str, str] | None = None, apps=("shop", "blog")):
    files = {
        "k8s/fleet-app/fleet-app.yaml": _contract(apps[0]),
        "k8s/applications/kustomization.yaml": f"resources: [platform, {apps[0]}]\n",
        "k8s/applications/platform/hpa.yaml": (
            "kind: HorizontalPodAutoscaler\n"
            "metadata: {name: '${APP_NAME}', namespace: applications}\n"
        ),
        "scripts/build.sh": 'docker build -t "$APP_NAME" .\n',
        **{f"k8s/applications/{a}/fleet-app.yaml": _contract(a) for a in apps},
        **{f"k8s/applications/{a}/deployment.yaml": f"metadata: {{name: {a}}}\n" for a in apps},
        **(extra or {}),
    }
    for rel_path, text in files.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return collector.collect(tmp_path, LIMITS)


def test_a_platform_that_names_no_app_with_two_contracts_is_swappable(tmp_path: Path) -> None:
    result = _fleet(tmp_path)

    assert result.coverage.status == "ok"
    [evidence] = result.evidence
    assert evidence.fact == {
        "contract_present": True,
        "application_count": 2,
        "platform_files_naming_an_app": 0,
        "platform_objects_with_literal_names": 0,
        "swappable": True,
    }
    assert evidence.source_path == "k8s/fleet-app/fleet-app.yaml"


def test_a_platform_file_naming_an_app_is_cited(tmp_path: Path) -> None:
    result = _fleet(tmp_path, {"policies/images.yaml": "allow: registry/blog:\n"})

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.fact["platform_files_naming_an_app"] == 1
    assert evidence.source_path == "policies/images.yaml"


def test_a_name_inside_a_longer_word_is_not_a_mention(tmp_path: Path) -> None:
    result = _fleet(tmp_path, {"scripts/x.sh": "echo blogger shop-front myshop\n"})

    assert result.evidence[0].fact["swappable"] is True


def test_one_app_or_no_contract_is_not_swappable(tmp_path: Path) -> None:
    assert _fleet(tmp_path / "one", apps=("shop",)).evidence[0].fact["swappable"] is False
    no_contract = tmp_path / "none"
    _fleet(no_contract)
    (no_contract / "k8s/fleet-app/fleet-app.yaml").unlink()
    result = collector.collect(no_contract, LIMITS)
    assert result.evidence[0].fact["contract_present"] is False
    assert result.evidence[0].fact["swappable"] is False


def test_unreadable_or_mismatched_input_makes_coverage_partial(tmp_path: Path) -> None:
    mismatched = _fleet(tmp_path / "a", {"k8s/applications/other/fleet-app.yaml": _contract("x")})
    assert mismatched.coverage.status == "partial"

    oversized = _fleet(
        tmp_path / "b", {"scripts/huge.sh": "x" * (LIMITS.max_manifest_file_bytes + 1)}
    )
    assert oversized.coverage.status == "partial"


def test_untracked_files_are_not_read(tmp_path: Path) -> None:
    _fleet(tmp_path, {"scripts/stray.sh": "shop\n"})
    tracked = frozenset(
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.rglob("*")
        if p.is_file() and p.name != "stray.sh"
    )

    result = collector.collect(tmp_path, LIMITS, tracked_paths=tracked)
    assert result.evidence[0].fact["swappable"] is True


def test_a_checkout_without_applications_yields_no_evidence(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.sh").write_text("echo hi\n", encoding="utf-8")

    result = collector.collect(tmp_path, LIMITS)
    assert result.evidence == ()
    assert result.coverage.status == "ok"


def test_a_platform_object_with_a_new_literal_name_is_coupling(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/applications/platform/hpa.yaml": (
                "kind: HorizontalPodAutoscaler\n"
                "metadata: {name: backend, namespace: applications}\n"
            )
        },
    )

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.fact["platform_objects_with_literal_names"] == 1
    assert evidence.source_path == "k8s/applications/platform/hpa.yaml"


def test_an_excluded_contract_leaves_the_verdict_unknown(tmp_path: Path) -> None:
    _fleet(tmp_path)
    result = collector.collect(tmp_path, LIMITS, excluded_paths=frozenset({"k8s/fleet-app"}))

    [evidence] = result.evidence
    assert result.coverage.status == "partial"
    assert "swappable" not in evidence.fact


def test_readable_coupling_decides_even_when_a_contract_is_unknown(tmp_path: Path) -> None:
    _fleet(tmp_path, {"policies/images.yaml": "allow: registry/blog:\n"})
    result = collector.collect(tmp_path, LIMITS, excluded_paths=frozenset({"k8s/fleet-app"}))

    assert result.evidence[0].fact["swappable"] is False


def test_a_missing_selected_contract_is_cited_at_a_tracked_file(tmp_path: Path) -> None:
    _fleet(tmp_path)
    (tmp_path / "k8s/fleet-app/fleet-app.yaml").unlink()

    [evidence] = collector.collect(tmp_path, LIMITS).evidence
    assert evidence.fact["swappable"] is False
    assert evidence.source_path == "k8s/applications/kustomization.yaml"


def test_controller_objects_outside_the_app_namespace_are_not_app_bound(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/flux-system/gotk.yaml": (
                "kind: NetworkPolicy\nmetadata: {name: allow-egress, namespace: flux-system}\n"
            )
        },
    )

    assert result.evidence[0].fact["swappable"] is True
