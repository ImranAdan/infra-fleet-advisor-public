import json
from pathlib import Path

import pytest

from infra_fleet_advisor.config.intents import IntentCatalog, IntentProposition
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.repository_settings_collector import (  # noqa: E501
    SNAPSHOT_SCHEMA,
    collect,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import (
    CHECK_DEFAULT_BRANCH_PROTECTED,
    CHECK_REPOSITORY_SECURITY_UPDATES_ENABLED,
    CHECK_SECRET_PROTECTION_ENABLED,
    compile_intents,
)

CHECKS = {
    "S-012": CHECK_REPOSITORY_SECURITY_UPDATES_ENABLED,
    "S-013": CHECK_SECRET_PROTECTION_ENABLED,
    "S-014": CHECK_DEFAULT_BRANCH_PROTECTED,
}


def _snapshot(tmp_path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "repository": "ImranAdan/infra-fleet-public",
        "fetched_at": "2026-10-10T20:00:00+00:00",
        "dependabot_alerts": True,
        "security_updates": True,
        "secret_scanning": True,
        "push_protection": True,
        "default_branch_protected": True,
        "reason": "",
    }
    data.update(overrides)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _statuses(path: Path) -> dict[str, str]:
    result = collect(path, "infra-fleet-public")
    catalog = IntentCatalog(
        digest="intent-md-v1:" + "a" * 64,
        propositions=tuple(
            IntentProposition(
                document_id="security",
                document_version="1.0",
                proposition_id=proposition,
                category="security",
                priority=None,
                statement="A repository setting is on.",
                check_key=check,
            )
            for proposition, check in CHECKS.items()
        ),
    )
    compilation = compile_intents(
        catalog,
        enabled_categories=frozenset({"security"}),
        evidence=result.evidence,
        coverage=(result.coverage,),
    )
    return {item.proposition_id: item.status for item in compilation.evaluations}


def test_all_settings_on_proves_every_position(tmp_path: Path) -> None:
    result = collect(_snapshot(tmp_path), "infra-fleet-public")

    assert result.coverage.status == "ok"
    assert len(result.evidence) == 3
    assert {e.source_path for e in result.evidence} == {
        ".github/dependabot.yml",
        "SECURITY.md",
        "AGENTS.md",
    }
    assert _statuses(_snapshot(tmp_path)) == dict.fromkeys(CHECKS, "satisfied")


@pytest.mark.parametrize(
    ("setting", "position"),
    [
        ("dependabot_alerts", "S-012"),
        ("security_updates", "S-012"),
        ("secret_scanning", "S-013"),
        ("push_protection", "S-013"),
        ("default_branch_protected", "S-014"),
    ],
)
def test_a_setting_off_diverges_only_its_position(
    tmp_path: Path, setting: str, position: str
) -> None:
    statuses = _statuses(_snapshot(tmp_path, **{setting: False}))

    assert statuses[position] == "divergent"
    assert all(status == "satisfied" for key, status in statuses.items() if key != position)


def test_an_unknown_setting_costs_every_proof_but_keeps_known_divergence(tmp_path: Path) -> None:
    statuses = _statuses(
        _snapshot(tmp_path, secret_scanning=None, default_branch_protected=False, reason="403")
    )

    assert statuses == {
        "S-012": "declared_unverified",
        "S-013": "declared_unverified",
        "S-014": "divergent",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "someone/else"},
        {"schema": "repository-settings/v1"},
        {"push_protection": "yes"},
        {"extra": 1},
    ],
)
def test_malformed_snapshot_never_satisfies(tmp_path: Path, overrides: dict[str, object]) -> None:
    result = collect(_snapshot(tmp_path, **overrides), "infra-fleet-public")

    assert result.evidence == ()
    assert result.coverage.status == "partial"
    assert set(_statuses(_snapshot(tmp_path, **overrides)).values()) == {"declared_unverified"}


def test_symlinked_or_missing_snapshot_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "link.json"
    link.symlink_to(_snapshot(tmp_path))

    assert collect(link, "infra-fleet-public").coverage.status == "partial"
    assert collect(tmp_path / "missing.json", "infra-fleet-public").coverage.status == "partial"
