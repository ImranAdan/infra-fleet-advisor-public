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
    CONCERN_TEMPLATES,
    CONCERN_TRIVY_IGNORE_UNFIXED,
    CONCERN_WILDCARD_IAM_PERMISSIONS,
    candidate_from_template,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_IAM_WILDCARD,
    EVIDENCE_KIND_TRIVY_GATE,
    GHA_COLLECTOR_ID,
    TF_IAM_COLLECTOR_ID,
)

CHECK_GITHUB_ACTIONS_USES_OIDC = "github_actions_uses_oidc"
CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS = "persistent_iam_avoids_wildcards"
CHECK_TRIVY_DOES_NOT_IGNORE_UNFIXED = "trivy_does_not_ignore_unfixed"


@dataclass(frozen=True, slots=True)
class IntentCheckDefinition:
    concern_key: str
    collector_id: str
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
            collector_id=GHA_COLLECTOR_ID,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_CREDENTIAL_METHOD,
                required_facts={"uses_oidc_only": False},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
        CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS: IntentCheckDefinition(
            concern_key=CONCERN_WILDCARD_IAM_PERMISSIONS,
            collector_id=TF_IAM_COLLECTOR_ID,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_IAM_WILDCARD,
                source_path_prefixes=("infrastructure/permanent",),
            ),
            can_prove_satisfaction=False,
        ),
        CHECK_TRIVY_DOES_NOT_IGNORE_UNFIXED: IntentCheckDefinition(
            concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
            collector_id=GHA_COLLECTOR_ID,
            rule=ConcernRule(
                category="security",
                evidence_kind=EVIDENCE_KIND_TRIVY_GATE,
                required_facts={"ignore_unfixed": True},
            ),
            can_prove_satisfaction=True,
            requires_relevant_evidence=True,
        ),
    }
)


def _is_relevant(item: Evidence, definition: IntentCheckDefinition) -> bool:
    rule = definition.rule
    return (
        item.collector_id == definition.collector_id
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
        if proposition.check_key is None:
            status = "declared_unverified"
            reason = "check_not_declared"
            evidence_ids = ()
        elif definition is None:
            status = "declared_unverified"
            reason = "check_not_registered"
            evidence_ids = ()
        elif proposition.category != definition.rule.category:
            raise PolicyError("intent check category does not match its trusted registry entry")
        elif proposition.category not in enabled_categories:
            status = "declared_unverified"
            reason = "category_not_enabled_by_policy"
            evidence_ids = ()
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
                collector_coverage = coverage_by_id.get(definition.collector_id)
                if collector_coverage is None:
                    status = "declared_unverified"
                    reason = "collector_not_run"
                elif collector_coverage.status != "ok":
                    status = "declared_unverified"
                    reason = "collector_incomplete"
                elif not definition.can_prove_satisfaction:
                    status = "declared_unverified"
                    reason = "collector_cannot_prove_satisfaction"
                elif definition.requires_relevant_evidence and not relevant:
                    status = "declared_unverified"
                    reason = "no_relevant_evidence"
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
