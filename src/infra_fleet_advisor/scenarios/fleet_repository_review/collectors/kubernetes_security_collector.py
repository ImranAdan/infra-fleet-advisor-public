"""Network, RBAC and TLS facts for what each deployment profile applies.

Each profile under `k8s/clusters/` is rendered in-process by profile_renderer,
so overlay patches are evaluated, not guessed. An object's facts are combined
across profiles: a protective fact must hold in every profile and a risky one
counts if any profile has it, so evidence identities stay stable. Without
profiles, raw manifests are evaluated as one set. HelmRelease chart output is
not rendered. Application workloads are Deployments sourced from
`k8s/applications/`.
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
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_renderer import (
    KUSTOMIZATION_FILES,
    render_profiles,
)

_APPLICATIONS = "k8s/applications/"
# Flux's generated install manifests are upstream platform code, not owner policy.
_GENERATED = "k8s/flux-system/"
_ISSUER_ANNOTATIONS = ("cert-manager.io/cluster-issuer", "cert-manager.io/issuer")
_BROAD_GROUPS = {"system:authenticated", "system:serviceaccounts"}
_MAX_RESOURCES = 2000
_MAX_PROFILES = 8
# Facts that protect: they must hold in every profile. Other booleans are risks
# that count when any profile has them.
_PROTECTIVE = frozenset(
    {
        "selected_by_ingress_policy",
        "ingress_restricted",
        "token_grants_nothing",
        "application_namespace",
        "acceptance_bounded",
        "tls_covers_hosts",
        "cert_manager_issuer",
        "https_enforced",
    }
)


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


def _evaluate(resources: list[_Resource]) -> tuple[list[Evidence], int]:
    """Evidence for one resource set; ambiguous identities are withheld."""
    failures = 0
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

    # Two declarations of one object in the same set carry conflicting facts;
    # one ID cannot hold both, so withhold every ambiguous identity.
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.evidence_id] = counts.get(item.evidence_id, 0) + 1
    duplicates = {eid for eid, count in counts.items() if count > 1}
    return [item for item in evidence if item.evidence_id not in duplicates], failures + len(
        duplicates
    )


def _combine(per_profile: dict[str, list[Evidence]]) -> list[Evidence]:
    """One record per object: protective facts hold everywhere, risks anywhere."""
    grouped: dict[str, list[tuple[str, Evidence]]] = {}
    for profile, items in per_profile.items():
        for item in items:
            grouped.setdefault(item.evidence_id, []).append((profile, item))
    combined = []
    for entries in grouped.values():
        first = entries[0][1]
        fact: dict[str, bool | str | int] = {}
        for key, value in first.fact.items():
            values = [item.fact.get(key) for _profile, item in entries]
            if isinstance(value, bool):
                fact[key] = all(values) if key in _PROTECTIVE else any(values)
            else:
                fact[key] = ", ".join(sorted({str(v) for v in values}))
        failing = [
            profile
            for profile, item in entries
            if any(item.fact.get(key) is False for key in _PROTECTIVE & set(item.fact))
        ]
        profiles = sorted(profile for profile, _item in entries)
        fact["profiles"] = ", ".join(profiles)
        fact["failing_profiles"] = ", ".join(sorted(failing))
        shown = next((item for profile, item in entries if profile in failing), first)
        combined.append(
            Evidence(
                evidence_id=first.evidence_id,
                kind=first.kind,
                # Cite the manifest of the profile the excerpt describes.
                source_path=shown.source_path,
                locator=first.locator,
                excerpt=f"[{', '.join(sorted(failing) or profiles)}] {shown.excerpt}"[:280],
                fact=fact,
                collector_id=first.collector_id,
                collector_version=first.collector_version,
            )
        )
    return combined


def _raw_resources(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str],
    tracked_paths: frozenset[str] | None,
) -> tuple[list[_Resource], list[str]]:
    manifests_dir = checkout_root / "k8s"
    checkout_real = checkout_root.resolve()
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
    unreadable = 0
    resources: list[_Resource] = []
    for path in files:
        rel_path = path.relative_to(checkout_root).as_posix()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                unreadable += 1
                continue
            if path.stat().st_size > limits.max_manifest_file_bytes:
                unreadable += 1
                continue
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError):
            unreadable += 1
            continue
        for document in documents:
            items = document.get("items") if isinstance(document, Mapping) else None
            for body in items if isinstance(items, list) else [document]:
                if isinstance(body, Mapping) and isinstance(body.get("kind"), str):
                    resources.append(_Resource(rel_path, body))
    gaps = []
    if unreadable:
        gaps.append(f"{unreadable} manifest file(s) could not be read")
    if len(eligible) > len(files):
        gaps.append(f"{len(eligible) - len(files)} manifest file(s) omitted by safety limit")
    return resources, gaps


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    if not (checkout_root / "k8s").is_dir():
        return CollectorResult((), CollectorCoverage(K8S_SECURITY_COLLECTOR_ID, "ok", 0))
    clusters = checkout_root / "k8s" / "clusters"
    directories = (
        sorted(path for path in clusters.iterdir() if path.is_dir()) if (clusters.is_dir()) else []
    )
    reasons: list[str] = []
    profiles = []
    for directory in directories:
        if any((directory / name).is_file() for name in KUSTOMIZATION_FILES):
            profiles.append(directory.name)
        else:
            # Flux can reconcile a directory without a kustomization file; it
            # would still deploy something this collector did not evaluate.
            reasons.append(f"{directory.name}: no kustomization file, profile not rendered")
    if len(profiles) > _MAX_PROFILES:
        reasons.append(f"{len(profiles) - _MAX_PROFILES} profile(s) omitted by safety limit")
        profiles = profiles[:_MAX_PROFILES]
    resource_sets: dict[str, list[_Resource]] = {}
    if profiles:
        renders = render_profiles(checkout_root, profiles, limits, tracked_paths, excluded_paths)
        for render in renders:
            reasons.extend(f"{render.profile}: {gap}" for gap in render.gaps)
            resource_sets[render.profile] = [
                _Resource(item.source_path, item.body) for item in render.resources
            ]
    else:
        resources, gaps = _raw_resources(checkout_root, limits, excluded_paths, tracked_paths)
        # Without profiles nothing was rendered, so nothing can be proven:
        # divergences still surface, satisfaction does not.
        reasons.append("no deployment profiles; manifests evaluated unrendered")
        reasons.extend(gaps)
        resource_sets["manifests"] = resources

    per_profile: dict[str, list[Evidence]] = {}
    failures = 0
    for profile, resources in resource_sets.items():
        if len(resources) > _MAX_RESOURCES:
            reasons.append(f"{profile}: resources omitted by safety limit")
            resources = resources[:_MAX_RESOURCES]
        per_profile[profile], profile_failures = _evaluate(resources)
        failures += profile_failures
    if failures:
        reasons.append(f"{failures} manifest or resource(s) could not be evaluated")
    ordered = tuple(sorted(_combine(per_profile), key=lambda item: item.evidence_id))
    return CollectorResult(
        ordered,
        CollectorCoverage(
            K8S_SECURITY_COLLECTOR_ID,
            "partial" if reasons else "ok",
            len(ordered),
            "; ".join(reasons)[:500] or None,
        ),
    )
