"""Network, RBAC and TLS facts from tracked Kubernetes manifests.

Reads raw manifests only: overlays are not rendered, so profile patches are
invisible. Application workloads are the Deployments under `k8s/applications/`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_EGRESS_ACCEPTANCE,
    EVIDENCE_KIND_INGRESS_HTTPS,
    EVIDENCE_KIND_INGRESS_RESTRICTION,
    EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
    K8S_SECURITY_COLLECTOR_ID,
    K8S_SECURITY_COLLECTOR_VERSION,
)

_APPLICATIONS = "k8s/applications/"
# Flux's generated install manifests are upstream platform code, not owner policy.
_GENERATED = "k8s/flux-system/"
_ISSUER_ANNOTATIONS = ("cert-manager.io/cluster-issuer", "cert-manager.io/issuer")
_BROAD_GROUPS = {"system:authenticated", "system:serviceaccounts"}
_MAX_RESOURCES = 2000


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


@dataclass(frozen=True, slots=True)
class _Resource:
    path: str
    body: Mapping[str, Any]

    @property
    def kind(self) -> str:
        return str(self.body.get("kind", ""))

    @property
    def name(self) -> str:
        return str((self.body.get("metadata") or {}).get("name", ""))

    @property
    def namespace(self) -> str:
        return str((self.body.get("metadata") or {}).get("namespace") or "default")


def _selects(selector: Any, labels: Mapping[str, Any]) -> bool | None:
    """Kubernetes label-selector semantics; None when the selector is malformed."""
    if not isinstance(selector, Mapping):
        return None
    match_labels = selector.get("matchLabels") or {}
    expressions = selector.get("matchExpressions") or []
    if not isinstance(match_labels, Mapping) or not isinstance(expressions, list):
        return None
    if any(labels.get(key) != value for key, value in match_labels.items()):
        return False
    for expression in expressions:
        if not isinstance(expression, Mapping):
            return None
        key, operator = str(expression.get("key")), expression.get("operator")
        values = expression.get("values") or []
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and labels.get(key) in values:
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            return None
    return True


def _constrains(selector: Any) -> bool:
    """An empty selector ({}) matches everything, so it names no peer."""
    return isinstance(selector, Mapping) and bool(
        selector.get("matchLabels") or selector.get("matchExpressions")
    )


def _peer_is_scoped(peer: Any) -> bool:
    """A peer names pods or namespaces by non-empty selectors; ipBlock never does."""
    if not isinstance(peer, Mapping) or "ipBlock" in peer:
        return False
    selectors = [peer[key] for key in ("podSelector", "namespaceSelector") if key in peer]
    return bool(selectors) and all(_constrains(selector) for selector in selectors)


def _rule_is_open(rule: Any, direction: str) -> bool:
    peers = rule.get(direction) if isinstance(rule, Mapping) else None
    return not peers or not all(_peer_is_scoped(peer) for peer in peers)


def _governs(policy: Mapping[str, Any], direction: str) -> bool:
    types = policy.get("policyTypes")
    if isinstance(types, list):
        return direction in types
    return direction == "Ingress" or "egress" in policy


def _evidence(
    kind: str, resource: _Resource, suffix: str, excerpt: str, fact: dict[str, Any]
) -> Evidence:
    locator = f"{resource.kind}/{resource.namespace}/{resource.name}{suffix}"
    return build_evidence(
        collector_id=K8S_SECURITY_COLLECTOR_ID,
        collector_version=K8S_SECURITY_COLLECTOR_VERSION,
        kind=kind,
        source_path=resource.path,
        locator=locator,
        excerpt=excerpt,
        fact=fact,
        identity_parts=(kind, resource.kind, resource.namespace, resource.name),
    )


def _workload_evidence(
    deployment: _Resource,
    policies: list[_Resource],
    bindings: list[_Resource],
    accounts: dict[tuple[str, str], Mapping[str, Any]],
) -> list[Evidence]:
    template = (deployment.body.get("spec") or {}).get("template") or {}
    labels = (template.get("metadata") or {}).get("labels") or {}
    pod = template.get("spec") or {}
    if not isinstance(labels, Mapping) or not isinstance(pod, Mapping):
        raise ValueError("deployment template is malformed")

    selecting = []
    for policy in policies:
        spec = policy.body.get("spec") or {}
        if policy.namespace != deployment.namespace or not _governs(spec, "Ingress"):
            continue
        selected = _selects(spec.get("podSelector"), labels)
        if selected is None:
            raise ValueError("network policy selector is malformed")
        if selected:
            selecting.append(policy)
    # Policies are additive: one open rule on any selecting policy admits all.
    open_rules = [
        policy.name
        for policy in selecting
        if any(_rule_is_open(rule, "from") for rule in (policy.body["spec"].get("ingress") or []))
    ]
    restricted = bool(selecting) and not open_rules

    account = str(pod.get("serviceAccountName") or "default")
    # The pod field wins; otherwise the ServiceAccount's own default applies.
    automount = pod.get(
        "automountServiceAccountToken",
        accounts.get((deployment.namespace, account), {}).get("automountServiceAccountToken"),
    )
    mounts = automount is not False
    granted_by = []
    for binding in bindings:
        for subject in binding.body.get("subjects") or []:
            if not isinstance(subject, Mapping):
                continue
            name, kind = subject.get("name"), subject.get("kind")
            namespace = subject.get("namespace") or binding.namespace
            if (
                (kind == "ServiceAccount" and name == account and namespace == deployment.namespace)
                or (kind == "Group" and name in _BROAD_GROUPS)
                or (kind == "Group" and name == f"system:serviceaccounts:{deployment.namespace}")
            ):
                granted_by.append(f"{binding.kind}/{binding.name}")
    return [
        _evidence(
            EVIDENCE_KIND_INGRESS_RESTRICTION,
            deployment,
            "/ingress",
            f"{len(selecting)} ingress policy(ies) select the pods"
            + (f"; open rules in {', '.join(open_rules[:5])}" if open_rules else ""),
            {"selected_by_ingress_policy": bool(selecting), "ingress_restricted": restricted},
        ),
        _evidence(
            EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
            deployment,
            "/serviceaccount",
            f"service account {account}, token mounted: {str(mounts).lower()}"
            + (f"; bound by {', '.join(granted_by[:5])}" if granted_by else ""),
            {
                "service_account": account,
                "mounts_token": mounts,
                "account_has_bindings": bool(granted_by),
                "token_grants_nothing": not (mounts and granted_by),
            },
        ),
    ]


def _egress_evidence(policy: _Resource, application_namespaces: set[str]) -> Evidence:
    spec = policy.body.get("spec") or {}
    permissive = _governs(spec, "Egress") and any(
        _rule_is_open(rule, "to") for rule in (spec.get("egress") or [])
    )
    in_scope = policy.namespace in application_namespaces
    return _evidence(
        EVIDENCE_KIND_EGRESS_ACCEPTANCE,
        policy,
        "/egress",
        f"permissive egress: {str(permissive).lower()} in namespace {policy.namespace}",
        {
            "permissive_egress": permissive,
            "application_namespace": in_scope,
            "acceptance_bounded": not permissive or in_scope,
        },
    )


def _https_evidence(ingress: _Resource) -> Evidence:
    spec = ingress.body.get("spec") or {}
    annotations = (ingress.body.get("metadata") or {}).get("annotations") or {}
    hosts = {rule.get("host") for rule in spec.get("rules") or [] if isinstance(rule, Mapping)}
    hosts.discard(None)
    tls_hosts = {
        host
        for entry in spec.get("tls") or []
        if isinstance(entry, Mapping)
        for host in entry.get("hosts") or []
    }
    issuer = any(annotations.get(key) for key in _ISSUER_ANNOTATIONS)
    redirect_off = (
        str(annotations.get("nginx.ingress.kubernetes.io/ssl-redirect", "")).lower() == "false"
    )
    covered = bool(hosts) and hosts <= tls_hosts
    return _evidence(
        EVIDENCE_KIND_INGRESS_HTTPS,
        ingress,
        "/https",
        f"hosts covered by TLS: {str(covered).lower()}; cert-manager issuer: "
        f"{str(issuer).lower()}; HTTP redirect disabled: {str(redirect_off).lower()}",
        {
            "tls_covers_hosts": covered,
            "cert_manager_issuer": issuer,
            "http_redirect_disabled": redirect_off,
            "https_enforced": covered and issuer and not redirect_off,
        },
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    manifests_dir = checkout_root / "k8s"
    checkout_real = checkout_root.resolve()
    if not manifests_dir.is_dir():
        return CollectorResult((), CollectorCoverage(K8S_SECURITY_COLLECTOR_ID, "ok", 0))
    eligible = [
        path
        for path in sorted(manifests_dir.rglob("*"))
        if path.suffix in {".yaml", ".yml"}
        and path.is_file()
        and (tracked_paths is None or path.relative_to(checkout_root).as_posix() in tracked_paths)
        and not any(
            path.relative_to(checkout_root).as_posix() == ex
            or path.relative_to(checkout_root).as_posix().startswith(f"{ex}/")
            for ex in excluded_paths
        )
    ]
    files = eligible[: limits.max_manifest_files]
    failures = 0
    resources: list[_Resource] = []
    for path in files:
        rel_path = path.relative_to(checkout_root).as_posix()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                failures += 1
                continue
            if path.stat().st_size > limits.max_manifest_file_bytes:
                failures += 1
                continue
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError):
            failures += 1
            continue
        for document in documents:
            items = document.get("items") if isinstance(document, Mapping) else None
            for body in items if isinstance(items, list) else [document]:
                if isinstance(body, Mapping) and isinstance(body.get("kind"), str):
                    resources.append(_Resource(rel_path, body))
    # A List can pack many resources into one bounded file; cap the work.
    resource_limit_reached = len(resources) > _MAX_RESOURCES
    resources = resources[:_MAX_RESOURCES]

    deployments = [
        r for r in resources if r.kind == "Deployment" and r.path.startswith(_APPLICATIONS)
    ]
    policies = [r for r in resources if r.kind == "NetworkPolicy"]
    bindings = [r for r in resources if r.kind in {"RoleBinding", "ClusterRoleBinding"}]
    application_namespaces = {deployment.namespace for deployment in deployments}
    accounts = {(r.namespace, r.name): r.body for r in resources if r.kind == "ServiceAccount"}

    evidence: list[Evidence] = []
    for deployment in deployments:
        try:
            evidence.extend(_workload_evidence(deployment, policies, bindings, accounts))
        except (ValueError, AttributeError, TypeError):
            failures += 1
    for resource in resources:
        try:
            if resource.kind == "NetworkPolicy" and not resource.path.startswith(_GENERATED):
                evidence.append(_egress_evidence(resource, application_namespaces))
            elif resource.kind == "Ingress":
                evidence.append(_https_evidence(resource))
        except (AttributeError, TypeError):
            failures += 1

    # A base and an overlay can declare the same object with different facts;
    # one ID cannot carry both, so withhold every ambiguous identity.
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.evidence_id] = counts.get(item.evidence_id, 0) + 1
    duplicates = {eid for eid, count in counts.items() if count > 1}
    evidence = [item for item in evidence if item.evidence_id not in duplicates]
    failures += len(duplicates)

    reasons = []
    if resource_limit_reached:
        reasons.append("resources omitted by safety limit")
    if failures:
        reasons.append(f"{failures} manifest or resource(s) could not be evaluated")
    if len(eligible) > len(files):
        reasons.append(f"{len(eligible) - len(files)} manifest file(s) omitted by safety limit")
    ordered = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    return CollectorResult(
        ordered,
        CollectorCoverage(
            K8S_SECURITY_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(ordered),
            "; ".join(reasons) or None,
        ),
    )
