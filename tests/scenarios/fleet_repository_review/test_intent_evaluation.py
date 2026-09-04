import pytest

from infra_fleet_advisor.config.intents import IntentCatalog, IntentProposition
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_CREDENTIAL_METHOD,
    EVIDENCE_KIND_IAM_WILDCARD,
    GHA_COLLECTOR_ID,
    TF_IAM_COLLECTOR_ID,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import (
    CHECK_GITHUB_ACTIONS_USES_OIDC,
    CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS,
    compile_intents,
)


def _catalog(check_key: str | None, category: str = "security") -> IntentCatalog:
    return IntentCatalog(
        digest="intent-md-v1:" + "a" * 64,
        propositions=(
            IntentProposition(
                document_id="security",
                document_version="1.0",
                proposition_id="S-001",
                category=category,
                priority=None,
                statement="The fleet uses the declared control.",
                check_key=check_key,
            ),
        ),
    )


def _evidence(
    *,
    collector_id: str = GHA_COLLECTOR_ID,
    kind: str = EVIDENCE_KIND_CREDENTIAL_METHOD,
    path: str = ".github/workflows/deploy.yml",
    fact: dict[str, bool | str | int] | None = None,
    digest: str = "a" * 16,
) -> Evidence:
    return Evidence(
        evidence_id=f"{collector_id}:{digest}",
        kind=kind,
        source_path=path,
        locator="resource",
        excerpt="bounded evidence",
        fact=fact or {},
        collector_id=collector_id,
        collector_version="1.0.0",
    )


def _coverage(collector_id: str, status: str = "ok") -> tuple[CollectorCoverage, ...]:
    return (CollectorCoverage(collector_id, status, 1),)


def test_oidc_intent_is_divergent_or_satisfied_from_complete_evidence() -> None:
    divergent = _evidence(fact={"uses_oidc_only": False})
    failed = compile_intents(
        _catalog(CHECK_GITHUB_ACTIONS_USES_OIDC),
        enabled_categories=frozenset({"security"}),
        evidence=(divergent,),
        coverage=_coverage(GHA_COLLECTOR_ID),
    )
    assert failed.evaluations[0].status == "divergent"
    assert failed.evaluations[0].evidence_ids == (divergent.evidence_id,)
    assert failed.divergence_candidates[0].evidence_ids == (divergent.evidence_id,)
    rule = next(iter(failed.concern_rules.values()))
    assert rule.priority == "high"

    compliant = _evidence(fact={"uses_oidc_only": True})
    passed = compile_intents(
        _catalog(CHECK_GITHUB_ACTIONS_USES_OIDC),
        enabled_categories=frozenset({"security"}),
        evidence=(compliant,),
        coverage=_coverage(GHA_COLLECTOR_ID),
    )
    assert passed.evaluations[0].status == "satisfied"


def test_missing_or_incomplete_evidence_is_never_treated_as_satisfied() -> None:
    no_evidence = compile_intents(
        _catalog(CHECK_GITHUB_ACTIONS_USES_OIDC),
        enabled_categories=frozenset({"security"}),
        evidence=(),
        coverage=_coverage(GHA_COLLECTOR_ID),
    )
    assert no_evidence.evaluations[0].status == "declared_unverified"
    assert no_evidence.evaluations[0].reason == "no_relevant_evidence"

    incomplete = compile_intents(
        _catalog(CHECK_GITHUB_ACTIONS_USES_OIDC),
        enabled_categories=frozenset({"security"}),
        evidence=(),
        coverage=_coverage(GHA_COLLECTOR_ID, "partial"),
    )
    assert incomplete.evaluations[0].reason == "collector_incomplete"


def test_persistent_iam_check_ignores_wildcards_outside_its_declared_scope() -> None:
    staging = _evidence(
        collector_id=TF_IAM_COLLECTOR_ID,
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        path="infrastructure/staging/iam.tf",
    )
    compilation = compile_intents(
        _catalog(CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS),
        enabled_categories=frozenset({"security"}),
        evidence=(staging,),
        coverage=_coverage(TF_IAM_COLLECTOR_ID),
    )
    assert compilation.evaluations[0].status == "declared_unverified"
    assert compilation.evaluations[0].reason == "collector_cannot_prove_satisfaction"

    persistent = _evidence(
        collector_id=TF_IAM_COLLECTOR_ID,
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        path="infrastructure/permanent/iam.tf",
    )
    compilation = compile_intents(
        _catalog(CHECK_PERSISTENT_IAM_AVOIDS_WILDCARDS),
        enabled_categories=frozenset({"security"}),
        evidence=(persistent,),
        coverage=_coverage(TF_IAM_COLLECTOR_ID),
    )
    assert compilation.evaluations[0].status == "divergent"


def test_unmapped_and_unknown_checks_are_explicitly_unverified() -> None:
    unmapped = compile_intents(
        _catalog(None),
        enabled_categories=frozenset({"security"}),
        evidence=(),
        coverage=(),
    )
    assert unmapped.evaluations[0].reason == "check_not_declared"
    assert not unmapped.concern_rules

    unknown = compile_intents(
        _catalog("future_check"),
        enabled_categories=frozenset({"security"}),
        evidence=(),
        coverage=(),
    )
    assert unknown.evaluations[0].reason == "check_not_registered"


def test_registered_check_cannot_be_relabelled_to_another_category() -> None:
    with pytest.raises(PolicyError, match="category does not match"):
        compile_intents(
            _catalog(CHECK_GITHUB_ACTIONS_USES_OIDC, category="reliability"),
            enabled_categories=frozenset({"security", "reliability"}),
            evidence=(),
            coverage=(),
        )
