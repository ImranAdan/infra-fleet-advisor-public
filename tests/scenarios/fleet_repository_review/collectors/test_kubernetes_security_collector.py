from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    kubernetes_security_collector as collector,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_EGRESS_ACCEPTANCE,
    EVIDENCE_KIND_INGRESS_HTTPS,
    EVIDENCE_KIND_INGRESS_RESTRICTION,
    EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)

DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata: {name: app, namespace: applications}
spec:
  template:
    metadata: {labels: {app: web}}
    spec:
      containers: [{name: app, image: x}]
"""
POLICY = """apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: web, namespace: %s}
spec:
  podSelector: {matchExpressions: [{key: app, operator: In, values: [web]}]}
  policyTypes: [Ingress, Egress]
  ingress:
    - from: [%s]
  egress:
    - {}
"""
SCOPED = "{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: ingress}}}"


def _facts(tmp_path: Path, files: dict[str, str], kind: str) -> list[dict[str, object]]:
    for rel_path, text in files.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    result = collector.collect(tmp_path, LIMITS)
    # Fixtures without k8s/clusters are evaluated unrendered, never proven.
    assert result.coverage.error_summary == "no deployment profiles; manifests evaluated unrendered"
    return [dict(item.fact) for item in result.evidence if item.kind == kind]


def test_ingress_is_restricted_only_when_every_selecting_rule_names_peers(tmp_path) -> None:
    cases = {
        SCOPED: True,
        "{ipBlock: {cidr: 0.0.0.0/0}}": False,
        "": False,
    }
    for peers, restricted in cases.items():
        [fact] = _facts(
            tmp_path,
            {
                "k8s/applications/app.yaml": DEPLOYMENT,
                "k8s/applications/policy.yaml": POLICY % ("applications", peers),
            },
            EVIDENCE_KIND_INGRESS_RESTRICTION,
        )
        assert fact["ingress_restricted"] is restricted, peers


def test_unselected_pods_are_not_restricted(tmp_path) -> None:
    other = (POLICY % ("applications", SCOPED)).replace("values: [web]", "values: [api]")
    [fact] = _facts(
        tmp_path,
        {"k8s/applications/app.yaml": DEPLOYMENT, "k8s/applications/policy.yaml": other},
        EVIDENCE_KIND_INGRESS_RESTRICTION,
    )

    assert fact["selected_by_ingress_policy"] is False
    assert fact["ingress_restricted"] is False


def test_permissive_egress_is_bounded_to_application_namespaces(tmp_path) -> None:
    facts = _facts(
        tmp_path,
        {
            "k8s/applications/app.yaml": DEPLOYMENT,
            "k8s/applications/policy.yaml": POLICY % ("applications", SCOPED),
            "k8s/infrastructure/policy.yaml": POLICY % ("observability", SCOPED),
            "k8s/flux-system/gotk.yaml": POLICY % ("flux-system", SCOPED),
        },
        EVIDENCE_KIND_EGRESS_ACCEPTANCE,
    )

    assert sorted(f["acceptance_bounded"] for f in facts) == [False, True]


def test_ingress_https_requires_tls_issuer_and_redirect(tmp_path) -> None:
    ingress = """apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: applications
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
%s
spec:
  tls: [{hosts: [app.example.com]}]
  rules: [{host: app.example.com}]
"""
    for annotation, enforced in (
        ("", True),
        ('    nginx.ingress.kubernetes.io/ssl-redirect: "false"', False),
    ):
        [fact] = _facts(
            tmp_path,
            {"k8s/profiles/aws/ingress.yaml": ingress % annotation},
            EVIDENCE_KIND_INGRESS_HTTPS,
        )
        assert fact["https_enforced"] is enforced, annotation


def test_mounted_token_is_privileged_only_with_bindings(tmp_path) -> None:
    binding = """apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: view, namespace: applications}
subjects: [{kind: %s, name: %s}]
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view}
"""
    for subject, grants in (
        (("ServiceAccount", "other"), False),
        (("ServiceAccount", "default"), True),
        (("Group", "system:serviceaccounts:applications"), True),
    ):
        [fact] = _facts(
            tmp_path,
            {
                "k8s/applications/app.yaml": DEPLOYMENT,
                "k8s/applications/binding.yaml": binding % subject,
            },
            EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
        )
        assert fact["token_grants_nothing"] is (not grants), subject

    no_mount = DEPLOYMENT.replace(
        "containers:", "automountServiceAccountToken: false\n      containers:"
    )
    [fact] = _facts(
        tmp_path,
        {"k8s/applications/app.yaml": no_mount},
        EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
    )
    assert fact["token_grants_nothing"] is True


def test_empty_peer_selectors_do_not_restrict(tmp_path) -> None:
    for peers in (
        "{namespaceSelector: {}}",
        "{podSelector: {}}",
        "{namespaceSelector: {}, podSelector: {matchLabels: {a: b}}}",
    ):
        [fact] = _facts(
            tmp_path,
            {
                "k8s/applications/app.yaml": DEPLOYMENT,
                "k8s/applications/policy.yaml": POLICY % ("applications", peers),
            },
            EVIDENCE_KIND_INGRESS_RESTRICTION,
        )
        assert fact["ingress_restricted"] is False, peers


def test_service_account_automount_default_is_honoured(tmp_path) -> None:
    account = (
        "apiVersion: v1\nkind: ServiceAccount\nmetadata: {name: default, namespace: applications}\n"
        "automountServiceAccountToken: false\n"
    )
    binding = (
        "apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\n"
        "metadata: {name: view, namespace: applications}\n"
        "subjects: [{kind: ServiceAccount, name: default}]\n"
        "roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view}\n"
    )
    [fact] = _facts(
        tmp_path,
        {
            "k8s/applications/app.yaml": DEPLOYMENT,
            "k8s/applications/sa.yaml": account,
            "k8s/applications/binding.yaml": binding,
        },
        EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
    )

    assert fact["mounts_token"] is False
    assert fact["token_grants_nothing"] is True


def test_duplicate_resource_identities_are_withheld(tmp_path) -> None:
    for rel_path in ("k8s/applications/app.yaml", "k8s/profiles/aws/app.yaml"):
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEPLOYMENT, encoding="utf-8")
    (tmp_path / "k8s/applications/copy.yaml").write_text(DEPLOYMENT, encoding="utf-8")

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"
    assert [e for e in result.evidence if e.kind == EVIDENCE_KIND_INGRESS_RESTRICTION] == []


def test_resource_count_is_bounded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(collector, "_MAX_RESOURCES", 1)
    path = tmp_path / "k8s" / "applications" / "app.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(DEPLOYMENT + "---\n" + POLICY % ("applications", SCOPED), encoding="utf-8")

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "partial"
    assert "safety limit" in (result.coverage.error_summary or "")


def _write(root, files: dict[str, str]) -> None:
    for rel_path, text in files.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


KUSTOMIZE = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
FLUX = """apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: apps, namespace: flux-system}
spec:
  path: ./k8s/profiles/%s
  sourceRef: {kind: GitRepository, name: flux-system}
"""
OPEN_PATCH = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [../../applications]
patches:
  - target: {kind: NetworkPolicy, name: web}
    patch: |-
      - op: replace
        path: /spec/ingress/0/from/0
        value: {ipBlock: {cidr: 0.0.0.0/0}}
"""


def test_a_profile_patch_that_opens_ingress_is_divergent_in_that_profile(tmp_path) -> None:
    base = KUSTOMIZE + "resources: [app.yaml, policy.yaml]\n"
    passthrough = KUSTOMIZE + "resources: [../../applications]\n"
    files = {
        "k8s/applications/kustomization.yaml": base,
        "k8s/applications/app.yaml": DEPLOYMENT,
        "k8s/applications/policy.yaml": POLICY % ("applications", SCOPED),
        "k8s/profiles/safe/kustomization.yaml": passthrough,
        "k8s/profiles/open/kustomization.yaml": OPEN_PATCH,
    }
    for profile in ("safe", "open"):
        files[f"k8s/clusters/{profile}/kustomization.yaml"] = KUSTOMIZE + "resources: [apps.yaml]\n"
        files[f"k8s/clusters/{profile}/apps.yaml"] = FLUX % profile
    _write(tmp_path, files)

    result = collector.collect(tmp_path, LIMITS)

    assert result.coverage.status == "ok"
    [fact] = [dict(e.fact) for e in result.evidence if e.kind == EVIDENCE_KIND_INGRESS_RESTRICTION]
    # The raw base is restricted; only rendering reveals the open profile.
    assert fact["ingress_restricted"] is False
    assert fact["profiles"] == "open, safe"
    assert fact["failing_profiles"] == "open"
