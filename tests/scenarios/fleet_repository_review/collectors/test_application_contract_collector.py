from pathlib import Path

import pytest

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
            "spec: {scaleTargetRef: {name: '${APP_NAME}'}}\n"
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
        "platform_objects_with_literal_bindings": 0,
        "selection_consistent": True,
        "uncontracted_application_sources": 0,
        "on_demand_launcher": False,
        "swappable": True,
    }
    assert evidence.source_path == "k8s/fleet-app/fleet-app.yaml"


def test_a_platform_file_naming_an_app_is_cited(tmp_path: Path) -> None:
    result = _fleet(tmp_path, {"policies/images.yaml": "allow: registry/blog:\n"})

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.fact["platform_files_naming_an_app"] == 1
    assert evidence.source_path == "policies/images.yaml"


def test_the_generic_acceptance_workflow_cannot_name_an_app(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {".github/workflows/local-kubernetes.yml": "matrix: {app: [shop, blog]}\n"},
    )

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.fact["platform_files_naming_an_app"] == 1
    assert evidence.source_path == ".github/workflows/local-kubernetes.yml"


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
    assert evidence.fact["platform_objects_with_literal_bindings"] == 1
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


@pytest.mark.parametrize(
    "selector",
    ("{}", "{matchLabels: {}}", "{matchExpressions: []}"),
)
def test_namespace_wide_network_policy_is_not_app_bound(tmp_path: Path, selector: str) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/infrastructure/namespaces/applications.yaml": (
                "kind: NetworkPolicy\n"
                "metadata: {name: default-deny-applications, namespace: applications}\n"
                f"spec: {{podSelector: {selector}, policyTypes: [Ingress]}}\n"
            )
        },
    )

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is True
    assert evidence.fact["platform_objects_with_literal_bindings"] == 0


@pytest.mark.parametrize(
    ("path", "manifest"),
    (
        (
            "k8s/applications/platform/hpa.yaml",
            "kind: HorizontalPodAutoscaler\n"
            "metadata: {name: '${APP_NAME}', namespace: applications}\n"
            "spec: {scaleTargetRef: {name: backend}}\n",
        ),
        (
            "k8s/applications/platform/canary.yaml",
            "kind: Canary\nmetadata: {name: '${APP_NAME}', namespace: applications}\n"
            "spec:\n  targetRef: {name: backend}\n  autoscalerRef: {name: '${APP_NAME}'}\n",
        ),
        (
            "k8s/profiles/aws-staging/applications/ingress.yaml",
            "kind: Ingress\nmetadata: {name: '${APP_NAME}', namespace: applications}\n"
            "spec:\n  rules:\n    - http:\n        paths:\n          - backend:\n"
            "              service: {name: backend}\n",
        ),
    ),
)
def test_a_literal_application_target_is_coupling(tmp_path: Path, path: str, manifest: str) -> None:
    result = _fleet(tmp_path, {path: manifest})

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.fact["platform_objects_with_literal_bindings"] == 1
    assert evidence.source_path == path


def test_optional_or_alternative_application_bindings_are_evaluated_when_present(
    tmp_path: Path,
) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/applications/platform/canary.yaml": (
                "kind: Canary\nmetadata: {name: '${APP_NAME}', namespace: applications}\n"
                "spec: {targetRef: {name: '${APP_NAME}'}}\n"
            ),
            "k8s/profiles/aws-staging/applications/ingress.yaml": (
                "kind: Ingress\nmetadata: {name: '${APP_NAME}', namespace: applications}\n"
                "spec: {defaultBackend: {service: {name: '${APP_NAME}'}}}\n"
            ),
        },
    )

    assert result.evidence[0].fact["swappable"] is True


def test_a_literal_default_ingress_backend_is_coupling(tmp_path: Path) -> None:
    path = "k8s/profiles/aws-staging/applications/ingress.yaml"
    result = _fleet(
        tmp_path,
        {
            path: (
                "kind: Ingress\nmetadata: {name: '${APP_NAME}', namespace: applications}\n"
                "spec: {defaultBackend: {service: {name: backend}}}\n"
            )
        },
    )

    [evidence] = result.evidence
    assert evidence.fact["swappable"] is False
    assert evidence.source_path == path


def test_an_unknown_app_contract_directory_is_not_treated_as_platform(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/applications/other/fleet-app.yaml": _contract("mismatch"),
            "k8s/applications/other/hpa.yaml": (
                "kind: HorizontalPodAutoscaler\n"
                "metadata: {name: other, namespace: applications}\n"
                "spec: {scaleTargetRef: {name: other}}\n"
            ),
        },
    )

    [evidence] = result.evidence
    assert result.coverage.status == "partial"
    assert "swappable" not in evidence.fact
    assert evidence.fact["platform_objects_with_literal_bindings"] == 0


def test_including_an_app_the_contract_does_not_select_is_divergent(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path, {"k8s/applications/kustomization.yaml": "resources: [platform, shop, blog]\n"}
    )

    [evidence] = result.evidence
    assert result.coverage.status == "ok"
    assert evidence.fact["selection_consistent"] is False
    assert evidence.fact["swappable"] is False


def test_a_selected_contract_that_drifts_from_the_app_contract_is_divergent(
    tmp_path: Path,
) -> None:
    drifted = _contract("shop").replace("APP_PORT: '80'", "APP_PORT: '81'")
    result = _fleet(tmp_path, {"k8s/fleet-app/fleet-app.yaml": drifted})

    assert result.evidence[0].fact["selection_consistent"] is False
    assert result.evidence[0].fact["swappable"] is False


@pytest.mark.parametrize(
    "selection",
    ("resources: [platform, ../../elsewhere/shop]\n", "resources: platform\n", "- [\n"),
)
def test_an_unresolvable_selection_leaves_the_verdict_unknown(
    tmp_path: Path, selection: str
) -> None:
    result = _fleet(tmp_path, {"k8s/applications/kustomization.yaml": selection})

    assert result.coverage.status == "partial"
    assert "swappable" not in result.evidence[0].fact


def test_application_source_without_a_contract_leaves_the_verdict_unknown(
    tmp_path: Path,
) -> None:
    result = _fleet(tmp_path, {"applications/wiki/Dockerfile": "FROM scratch\n"})

    [evidence] = result.evidence
    assert result.coverage.status == "partial"
    assert "wiki" in (result.coverage.error_summary or "")
    assert evidence.fact["uncontracted_application_sources"] == 1
    assert "swappable" not in evidence.fact


def test_contracted_application_sources_are_complete(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {"applications/shop/Dockerfile": "FROM x\n", "applications/blog/Dockerfile": "FROM x\n"},
    )

    assert result.coverage.status == "ok"
    assert result.evidence[0].fact["swappable"] is True


def test_a_platform_workload_in_the_app_namespace_is_an_app_of_its_own(tmp_path: Path) -> None:
    path = "k8s/applications/extras/deployment.yaml"
    result = _fleet(
        tmp_path,
        {path: "kind: Deployment\nmetadata: {name: wiki, namespace: applications}\n"},
    )

    [evidence] = result.evidence
    assert evidence.fact["platform_objects_with_literal_bindings"] == 1
    assert evidence.fact["swappable"] is False
    assert evidence.source_path == path


def test_an_app_bound_object_without_a_namespace_is_unknown(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/applications/platform/hpa.yaml": "kind: HorizontalPodAutoscaler\n"
            "metadata: {name: '${APP_NAME}'}\n"
        },
    )

    assert result.coverage.status == "partial"
    assert result.evidence[0].fact["platform_objects_with_literal_bindings"] == 0


def _patched(tmp_path: Path, patch: str, kind: str = "HorizontalPodAutoscaler"):
    return _fleet(
        tmp_path,
        {
            "k8s/profiles/local/applications/kustomization.yaml": (
                "resources: [../../../applications]\npatches:\n"
                f"  - target: {{kind: {kind}}}\n    patch: |-\n"
                + "".join(f"      {line}\n" for line in patch.splitlines())
            )
        },
    )


def test_a_patch_that_retargets_an_app_bound_field_literally_is_coupling(tmp_path: Path) -> None:
    result = _patched(tmp_path, "- op: replace\n  path: /spec/scaleTargetRef/name\n  value: wiki")

    [evidence] = result.evidence
    assert evidence.fact["platform_objects_with_literal_bindings"] == 1
    assert evidence.fact["swappable"] is False


@pytest.mark.parametrize(
    ("patch", "kind"),
    (
        ("- op: replace\n  path: /spec/maxReplicas\n  value: 3", "HorizontalPodAutoscaler"),
        ("- op: add\n  path: /metadata/name\n  value: ${APP_NAME}-x", "HorizontalPodAutoscaler"),
        ("- op: add\n  path: /metadata/name\n  value: fleet", "Gateway"),
    ),
)
def test_a_patch_outside_app_bound_fields_is_safe(tmp_path: Path, patch: str, kind: str) -> None:
    result = _patched(tmp_path, patch, kind)

    assert result.coverage.status == "ok"
    assert result.evidence[0].fact["swappable"] is True


@pytest.mark.parametrize(
    "patch",
    (
        "- op: add\n  path: /spec\n  value: {scaleTargetRef: {name: wiki}}",
        "- op: move\n  from: /x\n  path: /metadata/name",
        "kind: HorizontalPodAutoscaler\nmetadata: {name: wiki}",
    ),
)
def test_an_unresolvable_patch_leaves_the_verdict_unknown(tmp_path: Path, patch: str) -> None:
    result = _patched(tmp_path, patch)

    assert result.coverage.status == "partial"


def test_a_declared_on_demand_launcher_keeps_the_position_unproven(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/control-plane/rbac.yaml": (
                "kind: Role\nmetadata: {name: launcher, namespace: flux-system}\n"
                "rules:\n  - apiGroups: [kustomize.toolkit.fluxcd.io]\n"
                "    resources: [kustomizations]\n    verbs: [get, create]\n"
            )
        },
    )

    [evidence] = result.evidence
    assert result.coverage.status == "partial"
    assert "on-demand" in (result.coverage.error_summary or "")
    assert evidence.fact["on_demand_launcher"] is True
    assert evidence.fact["swappable"] is True


@pytest.mark.parametrize(
    "rbac",
    (
        "kind: Role\nmetadata: {name: reader, namespace: applications}\n"
        "rules: [{apiGroups: [apps], resources: [deployments], verbs: [list]}]\n",
        "kind: ClusterRole\nmetadata:\n  name: crd-controller\n"
        "  labels: {app.kubernetes.io/part-of: flux}\n"
        "rules: [{apiGroups: ['*'], resources: ['*'], verbs: ['*']}]\n",
    ),
)
def test_read_only_or_flux_rbac_is_not_a_launcher(tmp_path: Path, rbac: str) -> None:
    result = _fleet(tmp_path, {"k8s/control-plane/rbac.yaml": rbac})

    assert result.coverage.status == "ok"
    assert result.evidence[0].fact["on_demand_launcher"] is False


def test_a_broad_role_binding_is_a_launcher(tmp_path: Path) -> None:
    result = _fleet(
        tmp_path,
        {
            "k8s/control-plane/rbac.yaml": (
                "kind: ClusterRoleBinding\nmetadata: {name: dashboard}\n"
                "roleRef: {kind: ClusterRole, name: cluster-admin}\n"
            )
        },
    )

    assert result.evidence[0].fact["on_demand_launcher"] is True
