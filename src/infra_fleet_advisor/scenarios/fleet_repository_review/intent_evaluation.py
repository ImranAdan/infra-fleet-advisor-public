from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from infra_fleet_advisor.config.intents import IntentCatalog
from infra_fleet_advisor.core.contracts import ConcernRule, RawRecommendationCandidate
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.intent import IntentEvaluation, IntentEvaluationStatus
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_CI_CREDENTIALS_WITHOUT_OIDC,
    CONCERN_CONTAINER_HARDENING_INCOMPLETE,
    CONCERN_COST_TAGS_MISSING,
    CONCERN_CSRF_UNCOMPENSATED,
    CONCERN_DEPENDENCY_UPDATES_MISSING,
    CONCERN_DEPLOYMENT_ROLLOUT_CAPACITY,
    CONCERN_ECR_PUBLICATION_UNGATED,
    CONCERN_ECR_RETENTION_UNBOUNDED,
    CONCERN_EGRESS_ACCEPTANCE_EXCEEDED,
    CONCERN_EKS_EXPOSURE_BEYOND_STAGING,
    CONCERN_FLEET_AWS_ONBOARDING_INCOMPLETE,
    CONCERN_FLEET_LIFECYCLE_INCOMPLETE,
    CONCERN_FLEET_LOCAL_FIRST_USE_INCOMPLETE,
    CONCERN_IDLE_CAPACITY_UNSCHEDULED,
    CONCERN_INGRESS_HTTP_ALLOWED,
    CONCERN_INGRESS_UNRESTRICTED,
    CONCERN_LOG_RETENTION_UNBOUNDED,
    CONCERN_SERVICE_ACCOUNT_GRANTS_ACCESS,
    CONCERN_TEMPLATES,
    CONCERN_TRIVY_IGNORE_UNFIXED,
    CONCERN_WILDCARD_IAM_PERMISSIONS,
    CONCERN_WORKER_SCALING_STATIC,
    candidate_from_template,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    APP_CONFIG_COLLECTOR_ID,
    DEPENDENCY_UPDATE_COLLECTOR_ID,
    EVIDENCE_KIND_CONTAINER_HARDENING,
    EVIDENCE_KIND_COST_TAGS,
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_DEPENDENCY_UPDATES,
    EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
    EVIDENCE_KIND_ECR_LIFECYCLE,
    EVIDENCE_KIND_ECR_PUBLICATION_GATE,
    EVIDENCE_KIND_EGRESS_ACCEPTANCE,
    EVIDENCE_KIND_EKS_ENDPOINT,
    EVIDENCE_KIND_FLEET_LIFECYCLE,
    EVIDENCE_KIND_IAM_WILDCARD,
    EVIDENCE_KIND_IDLE_CAPACITY,
    EVIDENCE_KIND_INGRESS_HTTPS,
    EVIDENCE_KIND_INGRESS_RESTRICTION,
    EVIDENCE_KIND_LOG_RETENTION,
    EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
    EVIDENCE_KIND_SESSION_COOKIE,
    EVIDENCE_KIND_TRIVY_GATE,
    EVIDENCE_KIND_WORKER_SCALING,
    FLEET_LIFECYCLE_COLLECTOR_ID,
    GHA_COLLECTOR_ID,
    K8S_DEPLOYMENT_COLLECTOR_ID,
    K8S_SECURITY_COLLECTOR_ID,
    TF_COST_COLLECTOR_ID,
    TF_IAM_COLLECTOR_ID,
)

CHECK_GITHUB_ACTIONS_USES_OIDC = "github_actions_uses_oidc"
CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS = "persistent_iam_avoids_wildcards"
CHECK_TRIVY_DOES_NOT_IGNORE_UNFIXED = "trivy_does_not_ignore_unfixed"
CHECK_DEPLOYMENT_ROLLOUT_CAPACITY = "deployment_rollout_capacity"
CHECK_FLEET_PROFILES_EXPOSE_LIFECYCLE = "fleet_profiles_expose_lifecycle"
CHECK_FLEET_LOCAL_FIRST_USE = "fleet_local_first_use"
CHECK_FLEET_AWS_ONBOARDING = "fleet_aws_onboarding"
CHECK_APPLICATION_CONTAINERS_HARDENED = "application_containers_hardened"
CHECK_STAGING_LOG_RETENTION_BOUNDED = "staging_log_retention_bounded"
CHECK_ECR_LIFECYCLE_BOUNDED = "ecr_lifecycle_bounded"
CHECK_DEPENDENCY_UPDATES_CONFIGURED = "dependency_updates_configured"
CHECK_APPLICATION_INGRESS_RESTRICTED = "application_ingress_restricted"
CHECK_PERMISSIVE_EGRESS_BOUNDED = "permissive_egress_bounded"
CHECK_PUBLIC_INGRESS_HTTPS = "public_ingress_https"
CHECK_SERVICE_ACCOUNT_UNPRIVILEGED = "mounted_token_unprivileged"
CHECK_EKS_PUBLIC_ENDPOINT_STAGING_ONLY = "eks_public_endpoint_staging_only"
CHECK_SESSION_COOKIE_CSRF_COMPENSATED = "session_cookie_csrf_compensated"
CHECK_STAGING_CAPACITY_RELEASED = "staging_capacity_released_on_schedule"
CHECK_WORKER_GROUPS_DEMAND_SCALED = "worker_groups_demand_scaled"
CHECK_AWS_COST_TAGS = "aws_cost_allocation_tags"
CHECK_ECR_PUBLICATION_SCAN_GATED = "ecr_publication_scan_gated"


@dataclass(frozen=True, slots=True)
class IntentCheckDefinition:
    concern_key: str
    rule: ConcernRule
    can_prove_satisfaction: bool
    requires_relevant_evidence: bool = False


@dataclass(frozen=True, slots=True)
class ActiveIntent:
    document_id: str
    proposition_id: str
    check_key: str
    concern_key: str
    statement: str


@dataclass(frozen=True, slots=True)
class IntentCompilation:
    digest: str
    evaluations: tuple[IntentEvaluation, ...]
    active_intents: tuple[ActiveIntent, ...]
    concern_rules: Mapping[str, ConcernRule]
    divergence_candidates: tuple[RawRecommendationCandidate, ...]


@dataclass(frozen=True, slots=True)
class IntentRuleSet:
    active_intents: tuple[ActiveIntent, ...]
    concern_rules: Mapping[str, ConcernRule]


INTENT_CHECKS: Mapping[str, IntentCheckDefinition] = MappingProxyType(
    {
        CHECK_GITHUB_ACTIONS_USES_OIDC: IntentCheckDefinition(
            concern_key=CONCERN_CI_CREDENTIALS_WITHOUT_OIDC,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
                collector_id=GHA_COLLECTOR_ID,
                required_facts={"uses_oidc_only": False},
            ),
            # This collector can prove a configure-aws-credentials step conflicts
            # with the intent, but cannot rule out ambient or shell-provided
            # credentials elsewhere in the repository.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS: IntentCheckDefinition(
            concern_key=CONCERN_WILDCARD_IAM_PERMISSIONS,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_IAM_WILDCARD,
                collector_id=TF_IAM_COLLECTOR_ID,
                source_path_prefixes=("infrastructure/permanent",),
            ),
            can_prove_satisfaction=False,
        ),
        CHECK_TRIVY_DOES_NOT_IGNORE_UNFIXED: IntentCheckDefinition(
            concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_TRIVY_GATE,
                collector_id=GHA_COLLECTOR_ID,
                required_facts={"ignore_unfixed": True},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
        CHECK_DEPLOYMENT_ROLLOUT_CAPACITY: IntentCheckDefinition(
            concern_key=CONCERN_DEPLOYMENT_ROLLOUT_CAPACITY,
            rule=ConcernRule(
                category="reliability",
                evidence_kind=EVIDENCE_KIND_DEPLOYMENT_ROLLOUT_CAPACITY,
                collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
                source_path_prefixes=("k8s/applications",),
                required_facts={"retains_healthy_capacity": False},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
        CHECK_FLEET_PROFILES_EXPOSE_LIFECYCLE: IntentCheckDefinition(
            concern_key=CONCERN_FLEET_LIFECYCLE_INCOMPLETE,
            rule=ConcernRule(
                category="maintainability",
                evidence_kind=EVIDENCE_KIND_FLEET_LIFECYCLE,
                collector_id=FLEET_LIFECYCLE_COLLECTOR_ID,
                source_path_prefixes=("fleet",),
                required_facts={"common_lifecycle_complete": False},
            ),
            # Static parsing can prove the declared command surface is absent,
            # but cannot prove idempotence or runtime behavior from shell text.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_FLEET_LOCAL_FIRST_USE: IntentCheckDefinition(
            concern_key=CONCERN_FLEET_LOCAL_FIRST_USE_INCOMPLETE,
            rule=ConcernRule(
                category="maintainability",
                evidence_kind=EVIDENCE_KIND_FLEET_LIFECYCLE,
                collector_id=FLEET_LIFECYCLE_COLLECTOR_ID,
                source_path_prefixes=("scripts/fleet-profiles/local.sh",),
                required_facts={"local_first_use_complete": False},
            ),
            # Static source can prove a required control is absent, but cannot
            # prove downloads, Docker, or a real cluster work on every host.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_FLEET_AWS_ONBOARDING: IntentCheckDefinition(
            concern_key=CONCERN_FLEET_AWS_ONBOARDING_INCOMPLETE,
            rule=ConcernRule(
                category="maintainability",
                evidence_kind=EVIDENCE_KIND_FLEET_LIFECYCLE,
                collector_id=FLEET_LIFECYCLE_COLLECTOR_ID,
                source_path_prefixes=("scripts/fleet-profiles/aws-staging.sh",),
                required_facts={"aws_onboarding_complete": False},
            ),
            # Static text cannot prove AWS, HCP Terraform or GitHub calls succeed.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_APPLICATION_CONTAINERS_HARDENED: IntentCheckDefinition(
            concern_key=CONCERN_CONTAINER_HARDENING_INCOMPLETE,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_CONTAINER_HARDENING,
                collector_id=K8S_DEPLOYMENT_COLLECTOR_ID,
                source_path_prefixes=("k8s/applications",),
                required_facts={"all_containers_hardened": False},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
        CHECK_STAGING_LOG_RETENTION_BOUNDED: IntentCheckDefinition(
            concern_key=CONCERN_LOG_RETENTION_UNBOUNDED,
            rule=ConcernRule(
                category="cost",
                evidence_kind=EVIDENCE_KIND_LOG_RETENTION,
                collector_id=TF_COST_COLLECTOR_ID,
                source_path_prefixes=("infrastructure/staging",),
                required_facts={"bounded_retention": False},
            ),
            # AWS services and unrecognised modules can create log groups the
            # repository never declares, so absence of a long one proves nothing.
            can_prove_satisfaction=False,
        ),
        CHECK_ECR_LIFECYCLE_BOUNDED: IntentCheckDefinition(
            concern_key=CONCERN_ECR_RETENTION_UNBOUNDED,
            rule=ConcernRule(
                category="cost",
                evidence_kind=EVIDENCE_KIND_ECR_LIFECYCLE,
                collector_id=TF_COST_COLLECTOR_ID,
                required_facts={"bounded_lifecycle": False},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
        CHECK_DEPENDENCY_UPDATES_CONFIGURED: IntentCheckDefinition(
            concern_key=CONCERN_DEPENDENCY_UPDATES_MISSING,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_DEPENDENCY_UPDATES,
                collector_id=DEPENDENCY_UPDATE_COLLECTOR_ID,
                required_facts={"updated_monthly": False},
            ),
            # Alerts and security updates are repository settings the template
            # cannot declare, so full configuration still cannot prove S-010.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        # Raw manifests only: an unrendered overlay could add a policy, binding or
        # annotation, so these four Kubernetes security checks are divergence-only.
        CHECK_APPLICATION_INGRESS_RESTRICTED: IntentCheckDefinition(
            concern_key=CONCERN_INGRESS_UNRESTRICTED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_INGRESS_RESTRICTION,
                collector_id=K8S_SECURITY_COLLECTOR_ID,
                required_facts={"ingress_restricted": False},
            ),
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_PERMISSIVE_EGRESS_BOUNDED: IntentCheckDefinition(
            concern_key=CONCERN_EGRESS_ACCEPTANCE_EXCEEDED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_EGRESS_ACCEPTANCE,
                collector_id=K8S_SECURITY_COLLECTOR_ID,
                required_facts={"acceptance_bounded": False},
            ),
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_PUBLIC_INGRESS_HTTPS: IntentCheckDefinition(
            concern_key=CONCERN_INGRESS_HTTP_ALLOWED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_INGRESS_HTTPS,
                collector_id=K8S_SECURITY_COLLECTOR_ID,
                required_facts={"https_enforced": False},
            ),
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_SERVICE_ACCOUNT_UNPRIVILEGED: IntentCheckDefinition(
            concern_key=CONCERN_SERVICE_ACCOUNT_GRANTS_ACCESS,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_SERVICE_ACCOUNT_PRIVILEGE,
                collector_id=K8S_SECURITY_COLLECTOR_ID,
                required_facts={"token_grants_nothing": False},
            ),
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_EKS_PUBLIC_ENDPOINT_STAGING_ONLY: IntentCheckDefinition(
            concern_key=CONCERN_EKS_EXPOSURE_BEYOND_STAGING,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_EKS_ENDPOINT,
                collector_id=TF_COST_COLLECTOR_ID,
                required_facts={"exposure_accepted": False},
            ),
            # Every tracked EKS definition is read, but a cluster created outside
            # Terraform or by an unrecognised module stays invisible.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_SESSION_COOKIE_CSRF_COMPENSATED: IntentCheckDefinition(
            concern_key=CONCERN_CSRF_UNCOMPENSATED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_SESSION_COOKIE,
                collector_id=APP_CONFIG_COLLECTOR_ID,
                required_facts={"csrf_compensated": False},
            ),
            # Literal module-level config only; runtime overrides are invisible.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_STAGING_CAPACITY_RELEASED: IntentCheckDefinition(
            concern_key=CONCERN_IDLE_CAPACITY_UNSCHEDULED,
            rule=ConcernRule(
                category="cost",
                evidence_kind=EVIDENCE_KIND_IDLE_CAPACITY,
                collector_id=TF_COST_COLLECTOR_ID,
                required_facts={"scheduled_release": False},
            ),
            # A schedule outside the repository (an EventBridge rule, a person)
            # cannot be seen, and the usage window is the owner's to judge.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_WORKER_GROUPS_DEMAND_SCALED: IntentCheckDefinition(
            concern_key=CONCERN_WORKER_SCALING_STATIC,
            rule=ConcernRule(
                category="cost",
                evidence_kind=EVIDENCE_KIND_WORKER_SCALING,
                collector_id=TF_COST_COLLECTOR_ID,
                source_path_prefixes=("infrastructure/staging",),
                required_facts={"demand_scaled": False},
            ),
            # Whether an always-on minimum names the workload that needs it is a
            # judgement no static fact can settle, so C-002 is divergence-only.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_AWS_COST_TAGS: IntentCheckDefinition(
            concern_key=CONCERN_COST_TAGS_MISSING,
            rule=ConcernRule(
                category="cost",
                evidence_kind=EVIDENCE_KIND_COST_TAGS,
                collector_id=TF_COST_COLLECTOR_ID,
                required_facts={"cost_tags_incomplete": True},
            ),
            # Divergence needs a resource whose readable tags lack a key the
            # provider defaults also lack. Defaults do not reach every billed
            # resource (for example node-group instances), so none can prove C-005.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
        CHECK_ECR_PUBLICATION_SCAN_GATED: IntentCheckDefinition(
            concern_key=CONCERN_ECR_PUBLICATION_UNGATED,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_ECR_PUBLICATION_GATE,
                collector_id=GHA_COLLECTOR_ID,
                required_facts={"gated_by_blocking_scan": False},
            ),
            # Only recognised ECR login forms are publication paths; another
            # push mechanism would be invisible, so a clean result is unproven.
            can_prove_satisfaction=False,
            requires_relevant_evidence=True,
        ),
    }
)


def _is_relevant(item: Evidence, definition: IntentCheckDefinition) -> bool:
    rule = definition.rule
    return (
        item.collector_id == definition.rule.collector_id
        and item.kind == rule.evidence_kind
        and (
            not rule.source_path_prefixes
            or any(
                item.source_path == prefix or item.source_path.startswith(f"{prefix}/")
                for prefix in rule.source_path_prefixes
            )
        )
    )


def _is_divergent(item: Evidence, definition: IntentCheckDefinition) -> bool:
    return _is_relevant(item, definition) and all(
        item.fact.get(key) == value for key, value in definition.rule.required_facts.items()
    )


def compile_intent_rules(
    catalog: IntentCatalog, *, enabled_categories: frozenset[str]
) -> IntentRuleSet:
    """Bind declared check identifiers to static rules without executing configuration."""
    active_intents: list[ActiveIntent] = []
    concern_rules: dict[str, ConcernRule] = {}
    for proposition in catalog.propositions:
        if proposition.check_key is None:
            continue
        definition = INTENT_CHECKS.get(proposition.check_key)
        if definition is None:
            continue
        if proposition.category != definition.rule.category:
            raise PolicyError("intent check category does not match its trusted registry entry")
        if proposition.category not in enabled_categories:
            continue
        if definition.concern_key in concern_rules:
            raise PolicyError("multiple intent checks map to one concern")
        priority = proposition.priority or CONCERN_TEMPLATES[definition.concern_key].priority
        concern_rules[definition.concern_key] = replace(definition.rule, priority=priority)
        active_intents.append(
            ActiveIntent(
                document_id=proposition.document_id,
                proposition_id=proposition.proposition_id,
                check_key=proposition.check_key,
                concern_key=definition.concern_key,
                statement=proposition.statement,
            )
        )
    return IntentRuleSet(tuple(active_intents), MappingProxyType(concern_rules))


def compile_intents(
    catalog: IntentCatalog,
    *,
    enabled_categories: frozenset[str],
    evidence: tuple[Evidence, ...],
    coverage: tuple[CollectorCoverage, ...],
) -> IntentCompilation:
    """Resolve declarative propositions only through the trusted check registry."""
    coverage_by_id = {record.collector_id: record for record in coverage}
    if len(coverage_by_id) != len(coverage):
        raise PolicyError("collector coverage contains duplicate identities")

    rule_set = compile_intent_rules(catalog, enabled_categories=enabled_categories)
    rules_by_check = {
        active.check_key: rule_set.concern_rules[active.concern_key]
        for active in rule_set.active_intents
    }
    evaluations: list[IntentEvaluation] = []
    for proposition in catalog.propositions:
        status: IntentEvaluationStatus
        reason: str
        evidence_ids: tuple[str, ...]
        evaluation_priority = proposition.priority
        definition = (
            INTENT_CHECKS.get(proposition.check_key) if proposition.check_key is not None else None
        )
        if proposition.category not in enabled_categories:
            status = "declared_unverified"
            reason = "category_not_enabled_by_policy"
            evidence_ids = ()
        elif proposition.check_key is None:
            status = "declared_unverified"
            reason = "check_not_declared"
            evidence_ids = ()
        elif definition is None:
            status = "declared_unverified"
            reason = "check_not_registered"
            evidence_ids = ()
        elif proposition.category != definition.rule.category:
            raise PolicyError("intent check category does not match its trusted registry entry")
        else:
            rule = rules_by_check[proposition.check_key]
            evaluation_priority = rule.priority
            relevant = tuple(item for item in evidence if _is_relevant(item, definition))
            divergent = tuple(item for item in relevant if _is_divergent(item, definition))
            if divergent:
                status = "divergent"
                reason = "evidence_conflicts_with_intent"
                evidence_ids = tuple(sorted(item.evidence_id for item in divergent))
            else:
                collector_coverage = coverage_by_id.get(definition.rule.collector_id)
                if collector_coverage is None:
                    status = "declared_unverified"
                    reason = "collector_not_run"
                elif collector_coverage.status != "ok":
                    status = "declared_unverified"
                    reason = "collector_incomplete"
                elif definition.requires_relevant_evidence and not relevant:
                    status = "declared_unverified"
                    reason = "no_relevant_evidence"
                elif not definition.can_prove_satisfaction:
                    status = "declared_unverified"
                    reason = "collector_cannot_prove_satisfaction"
                else:
                    status = "satisfied"
                    reason = "complete_evidence_supports_intent"
                evidence_ids = ()

        evaluations.append(
            IntentEvaluation(
                document_id=proposition.document_id,
                proposition_id=proposition.proposition_id,
                category=proposition.category,
                priority=evaluation_priority,
                statement=proposition.statement,
                check_key=proposition.check_key,
                status=status,
                evidence_ids=evidence_ids,
                reason=reason,
            )
        )

    active_by_check = {item.check_key: item for item in rule_set.active_intents}
    divergence_candidates = tuple(
        candidate_from_template(
            active_by_check[evaluation.check_key].concern_key,
            evaluation.evidence_ids,
            evaluation.priority,
        )
        for evaluation in evaluations
        if evaluation.status == "divergent" and evaluation.check_key is not None
    )

    return IntentCompilation(
        digest=catalog.digest,
        evaluations=tuple(evaluations),
        active_intents=rule_set.active_intents,
        concern_rules=rule_set.concern_rules,
        divergence_candidates=divergence_candidates,
    )
