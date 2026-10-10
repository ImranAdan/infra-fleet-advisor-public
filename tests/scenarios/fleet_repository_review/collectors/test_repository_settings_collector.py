import json
from pathlib import Path

import pytest

from infra_fleet_advisor.config.intents import IntentCatalog, IntentProposition
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.repository_settings_collector import (  # noqa: E501
    SNAPSHOT_SCHEMA,
    collect,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.intent_evaluation import (
    CHECK_REPOSITORY_SECURITY_UPDATES_ENABLED,
    compile_intents,
)


def _snapshot(tmp_path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "repository": "ImranAdan/infra-fleet-public",
        "fetched_at": "2026-10-10T20:00:00+00:00",
        "dependabot_alerts": True,
        "security_updates": True,
        "reason": "",
    }
    data.update(overrides)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _s012(path: Path) -> str:
    result = collect(path, "infra-fleet-public")
    catalog = IntentCatalog(
        digest="intent-md-v1:" + "a" * 64,
        propositions=(
            IntentProposition(
                document_id="security",
                document_version="1.0",
                proposition_id="S-012",
                category="security",
                priority=None,
                statement="Dependabot alerts and security updates are enabled.",
                check_key=CHECK_REPOSITORY_SECURITY_UPDATES_ENABLED,
            ),
        ),
    )
    compilation = compile_intents(
        catalog,
        enabled_categories=frozenset({"security"}),
        evidence=result.evidence,
        coverage=(result.coverage,),
    )
    return compilation.evaluations[0].status


def test_both_settings_on_proves_s012(tmp_path: Path) -> None:
    result = collect(_snapshot(tmp_path), "infra-fleet-public")

    assert result.coverage.status == "ok"
    (evidence,) = result.evidence
    assert evidence.fact == {"dependabot_alerts": True, "security_updates": True, "enabled": True}
    assert evidence.source_path == ".github/dependabot.yml"
    assert "Dependabot alerts on, Dependabot security updates on" in evidence.excerpt
    assert _s012(_snapshot(tmp_path)) == "satisfied"


@pytest.mark.parametrize("overrides", [{"dependabot_alerts": False}, {"security_updates": False}])
def test_either_setting_off_diverges(tmp_path: Path, overrides: dict[str, object]) -> None:
    assert _s012(_snapshot(tmp_path, **overrides)) == "divergent"


@pytest.mark.parametrize(
    "overrides",
    [
        {"dependabot_alerts": None, "reason": "automated-security-fixes returned HTTP 403"},
        {"repository": "someone/else"},
        {"schema": "repository-settings/v0"},
        {"dependabot_alerts": "yes"},
        {"extra": 1},
    ],
)
def test_unknown_or_malformed_snapshot_never_satisfies(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    result = collect(_snapshot(tmp_path, **overrides), "infra-fleet-public")

    assert result.evidence == ()
    assert result.coverage.status == "partial"
    assert _s012(_snapshot(tmp_path, **overrides)) == "declared_unverified"


def test_symlinked_or_unreadable_snapshot_is_rejected(tmp_path: Path) -> None:
    target = _snapshot(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(target)

    assert collect(link, "infra-fleet-public").coverage.status == "partial"
    assert collect(tmp_path / "missing.json", "infra-fleet-public").coverage.status == "partial"
