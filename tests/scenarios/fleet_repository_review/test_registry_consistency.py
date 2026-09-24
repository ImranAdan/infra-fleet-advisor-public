"""The check registry, concern templates, intent catalog and drills agree.

Adding a check touches several hand-maintained tables. A mismatch between them
is otherwise only discovered at runtime, as an unregistered check silently
leaving a position unverified or a drill naming a position nothing checks.
"""

from pathlib import Path

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.runtime.drill import load_drills
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import CONCERN_TEMPLATES
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import TAXONOMY
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import (
    INTENT_CHECKS,
)

ROOT = Path(__file__).parents[3]
CATALOG = load_intent_catalog(ROOT / "intent", TAXONOMY)
DECLARED = {p.check_key: p for p in CATALOG.propositions if p.check_key is not None}


def test_every_registered_check_has_a_matching_concern_template() -> None:
    for check, definition in INTENT_CHECKS.items():
        template = CONCERN_TEMPLATES.get(definition.concern_key)
        assert template is not None, check
        assert template.category == definition.rule.category, check


# Registered checks the owner's catalog deliberately does not declare, and why.
UNUSED_BY_THIS_OWNER = {
    # S-011's caveat accepts unfixed Critical/High findings; the owner checks
    # scan-gated publication instead. Kept for catalogs that make the other call.
    "trivy_does_not_ignore_unfixed",
}


def test_every_declared_check_is_registered() -> None:
    # A declared but unregistered check leaves its position silently unverified.
    assert set(DECLARED) <= set(INTENT_CHECKS)


def test_every_registered_check_is_used_or_explained() -> None:
    assert set(INTENT_CHECKS) - set(DECLARED) == UNUSED_BY_THIS_OWNER


def test_each_check_lives_in_its_propositions_category() -> None:
    for check, proposition in DECLARED.items():
        assert INTENT_CHECKS[check].rule.category == proposition.category, check


def test_every_drill_targets_a_checked_position() -> None:
    checked = {p.proposition_id for p in DECLARED.values()}
    drills = load_drills(ROOT / "drills" / "fleet-mutations.yaml")

    assert {drill.proposition for drill in drills} <= checked
    # Every checked position is exercised by at least one drill.
    assert checked <= {drill.proposition for drill in drills}
