from pathlib import Path

import pytest

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import platform_collector
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CANARY_ROLLBACK,
    EVIDENCE_KIND_DECLARED_FOOTPRINT,
    EVIDENCE_KIND_DISRUPTION_BUDGET,
    EVIDENCE_KIND_DORA_COVERAGE,
    EVIDENCE_KIND_HELM_RECOVERY,
    EVIDENCE_KIND_MANIFEST_REACHABILITY,
    EVIDENCE_KIND_MESSAGING_CONTRACT,
    EVIDENCE_KIND_METRICS_RETENTION,
    EVIDENCE_KIND_POD_SECURITY,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)
KUSTOMIZE = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
FLUX = """apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: apps, namespace: flux-system}
spec:
  path: ./k8s/profiles/%s
  sourceRef: {kind: GitRepository, name: flux-system}
"""
APP = """apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: applications}
spec:
  template:
    metadata: {labels: {app: web}}
    spec:
      containers:
        - name: web
          image: app
          resources: {requests: {cpu: 50m, memory: 64Mi}}
"""
NAMESPACE = """apiVersion: v1
kind: Namespace
metadata:
  name: applications
  labels: {pod-security.kubernetes.io/enforce: restricted}
"""
CANARY = """apiVersion: flagger.app/v1beta1
kind: Canary
metadata: {name: web, namespace: applications}
spec:
  targetRef: {apiVersion: apps/v1, kind: Deployment, name: web}
  analysis:
    maxWeight: 50
    threshold: 3
    metrics: [{name: error-rate}]
"""
HPA = """apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: web, namespace: applications}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: web}
  minReplicas: 1
"""
PDB = """apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: {name: web-primary, namespace: applications}
spec:
  minAvailable: 1
  selector: {matchLabels: {app: web-primary}}
"""
HELM = """apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata: {name: kube-prometheus-stack, namespace: observability}
spec:
  interval: 10m
  timeout: 10m
  chart: {spec: {chart: kube-prometheus-stack}}
  install: {remediation: {retries: 3}}
  upgrade: {remediation: {retries: 3}}
  values:
    prometheus:
      prometheusSpec:
        retention: 2d
        retentionSize: 1GB
        resources: {requests: {cpu: 200m, memory: 512Mi}}
"""
AWS_PATCH = """  - target: {kind: HorizontalPodAutoscaler}
    patch: |-
      - op: replace
        path: /spec/minReplicas
        value: 2
"""


def _fleet() -> dict[str, str]:
    files = {
        "k8s/applications/platform/kustomization.yaml": KUSTOMIZE
        + "resources: [app.yaml, namespace.yaml, canary.yaml, hpa.yaml]\n",
        "k8s/applications/platform/app.yaml": APP,
        "k8s/applications/platform/namespace.yaml": NAMESPACE,
        "k8s/applications/platform/canary.yaml": CANARY,
        "k8s/applications/platform/hpa.yaml": HPA,
        "k8s/infrastructure/kustomization.yaml": KUSTOMIZE + "resources: [helm.yaml]\n",
        "k8s/infrastructure/helm.yaml": HELM,
        "k8s/profiles/local/kustomization.yaml": KUSTOMIZE
        + "resources: [../../applications/platform, ../../infrastructure]\n",
        "k8s/profiles/aws-staging/kustomization.yaml": KUSTOMIZE
        + "resources: [../../applications/platform, ../../infrastructure, pdb.yaml]\n"
        + "patches:\n"
        + AWS_PATCH,
        "k8s/profiles/aws-staging/pdb.yaml": PDB,
    }
    for profile in ("local", "aws-staging"):
        files[f"k8s/clusters/{profile}/kustomization.yaml"] = KUSTOMIZE + "resources: [apps.yaml]\n"
        files[f"k8s/clusters/{profile}/apps.yaml"] = FLUX % profile
    return files


def _collect(root: Path, files: dict[str, str]) -> platform_collector.CollectorResult:
    for rel_path, text in files.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return platform_collector.collect(root, LIMITS, frozenset(), frozenset(files))


def _facts(result: platform_collector.CollectorResult, kind: str) -> list[dict[str, object]]:
    return [dict(item.fact) for item in result.evidence if item.kind == kind]


def test_a_well_operated_fleet_satisfies_every_platform_fact(tmp_path) -> None:
    result = _collect(tmp_path, _fleet())

    assert result.coverage.status == "ok"
    assert [f["recovers"] for f in _facts(result, EVIDENCE_KIND_HELM_RECOVERY)] == [True]
    assert [f["canary_rolls_back"] for f in _facts(result, EVIDENCE_KIND_CANARY_ROLLBACK)] == [True]
    [drain] = _facts(result, EVIDENCE_KIND_DISRUPTION_BUDGET)
    assert (drain["minimum_replicas"], drain["budgets"], drain["survives_drain"]) == (2, 1, True)
    assert drain["profiles"] == "aws-staging"
    [security] = _facts(result, EVIDENCE_KIND_POD_SECURITY)
    assert security["enforces_restricted"] is True
    [retention] = _facts(result, EVIDENCE_KIND_METRICS_RETENTION)
    assert retention["retention_bounded"] is True
    [footprint] = _facts(result, EVIDENCE_KIND_DECLARED_FOOTPRINT)
    # 50m + 200m CPU and 64Mi + 512Mi memory, local profile only.
    assert (footprint["cpu_millicores"], footprint["memory_mib"]) == (250, 576)
    assert footprint["within_budget"] is True
    [reach] = _facts(result, EVIDENCE_KIND_MANIFEST_REACHABILITY)
    assert (reach["platform_manifests"], reach["unreached"], reach["all_reached"]) == (14, 0, True)


@pytest.mark.parametrize(
    ("path", "find", "replace", "kind", "fact"),
    [
        (
            "k8s/infrastructure/helm.yaml",
            "  timeout: 10m\n",
            "",
            EVIDENCE_KIND_HELM_RECOVERY,
            "recovers",
        ),
        (
            "k8s/infrastructure/helm.yaml",
            "upgrade: {remediation: {retries: 3}}",
            "upgrade: {remediation: {retries: 3, strategy: uninstall}}",
            EVIDENCE_KIND_HELM_RECOVERY,
            "recovers",
        ),
        (
            "k8s/applications/platform/canary.yaml",
            "maxWeight: 50",
            "maxWeight: 100",
            EVIDENCE_KIND_CANARY_ROLLBACK,
            "canary_rolls_back",
        ),
        (
            "k8s/applications/platform/canary.yaml",
            "    metrics: [{name: error-rate}]\n",
            "",
            EVIDENCE_KIND_CANARY_ROLLBACK,
            "canary_rolls_back",
        ),
        (
            "k8s/applications/platform/canary.yaml",
            "[{name: error-rate}]",
            "[]",
            EVIDENCE_KIND_CANARY_ROLLBACK,
            "canary_rolls_back",
        ),
        (
            "k8s/applications/platform/namespace.yaml",
            "restricted",
            "baseline",
            EVIDENCE_KIND_POD_SECURITY,
            "enforces_restricted",
        ),
        (
            "k8s/infrastructure/helm.yaml",
            "        retentionSize: 1GB\n",
            "",
            EVIDENCE_KIND_METRICS_RETENTION,
            "retention_bounded",
        ),
        (
            "k8s/infrastructure/helm.yaml",
            "cpu: 200m",
            "cpu: '1'",
            EVIDENCE_KIND_DECLARED_FOOTPRINT,
            "within_budget",
        ),
        (
            "k8s/infrastructure/helm.yaml",
            "memory: 512Mi",
            "memory: 2Gi",
            EVIDENCE_KIND_DECLARED_FOOTPRINT,
            "within_budget",
        ),
        # A budget on the canary's own pods protects nothing Flagger serves.
        (
            "k8s/profiles/aws-staging/pdb.yaml",
            "app: web-primary",
            "app: web-canary",
            EVIDENCE_KIND_DISRUPTION_BUDGET,
            "survives_drain",
        ),
        (
            "k8s/profiles/aws-staging/kustomization.yaml",
            "value: 2",
            "value: 1",
            EVIDENCE_KIND_DISRUPTION_BUDGET,
            "survives_drain",
        ),
        (
            "k8s/applications/platform/kustomization.yaml",
            " canary.yaml,",
            "",
            EVIDENCE_KIND_MANIFEST_REACHABILITY,
            "all_reached",
        ),
    ],
)
def test_one_regression_turns_its_fact_false(tmp_path, path, find, replace, kind, fact) -> None:
    files = _fleet()
    assert find in files[path]
    files[path] = files[path].replace(find, replace)

    result = _collect(tmp_path, files)

    assert [f[fact] for f in _facts(result, kind)] == [False]


def test_an_unreached_file_is_named_but_bootstrap_and_catalog_are_not(tmp_path) -> None:
    files = _fleet()
    files["k8s/infrastructure/orphan.yaml"] = HPA
    files["k8s/flux-system/gotk-components.yaml"] = HPA
    files["k8s/applications/podinfo/deployment.yaml"] = APP

    result = _collect(tmp_path, files)

    [reach] = [e for e in result.evidence if e.kind == EVIDENCE_KIND_MANIFEST_REACHABILITY]
    assert reach.fact["unreached"] == 1
    assert reach.source_path == "k8s/infrastructure/orphan.yaml"


def test_an_incomplete_render_proves_no_reachability(tmp_path) -> None:
    files = _fleet()
    files["k8s/profiles/local/kustomization.yaml"] += "resources: [missing.yaml]\n"

    result = _collect(tmp_path, files)

    assert result.coverage.status == "partial"
    assert _facts(result, EVIDENCE_KIND_MANIFEST_REACHABILITY) == []


CONTRACT = """apiVersion: v1
kind: ConfigMap
metadata: {name: fleet-app, namespace: flux-system}
data:
  APP_NAME: chat
%s"""
MESSAGING_APP = APP.replace(
    "          image: app\n",
    "          image: app\n          env: [{name: NATS_URL, value: 'nats://nats.messaging.svc:4222'}]\n",
)


@pytest.mark.parametrize(
    ("contract_line", "declared"),
    [
        ("  APP_MESSAGING_PREFIX: chat\n", True),
        ("", False),
        ("  APP_MESSAGING_PREFIX: Chat!\n", False),
    ],
)
def test_messaging_apps_must_declare_a_valid_prefix(tmp_path, contract_line, declared) -> None:
    files = {
        "k8s/applications/chat/deployment.yaml": MESSAGING_APP,
        "k8s/applications/chat/fleet-app.yaml": CONTRACT % contract_line,
        # An app without NATS_URL owes no prefix.
        "k8s/applications/quiet/deployment.yaml": APP,
        "k8s/applications/quiet/fleet-app.yaml": CONTRACT % "",
    }

    result = _collect(tmp_path, files)

    assert _facts(result, EVIDENCE_KIND_MESSAGING_CONTRACT) == [{"declares_prefix": declared}]


DORA = """name: DORA Metrics
on:
  workflow_run:
    workflows:
      - Web Publish
"""


@pytest.mark.parametrize(("name", "feeds"), [("Web Publish", True), ("Chat Publish", False)])
def test_publish_workflows_must_feed_dora(tmp_path, name, feeds) -> None:
    files = {
        ".github/workflows/dora-metrics.yml": DORA,
        ".github/workflows/web-publish.yml": f"name: {name}\non: push\n",
        ".github/workflows/ci.yml": "name: CI\non: push\n",
    }

    result = _collect(tmp_path, files)

    assert _facts(result, EVIDENCE_KIND_DORA_COVERAGE) == [{"feeds_dora": feeds}]
