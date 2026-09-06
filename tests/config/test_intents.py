from pathlib import Path

import pytest

from infra_fleet_advisor.config.intents import load_intent_catalog
from infra_fleet_advisor.core.errors import PolicyError

TAXONOMY = frozenset({"security", "reliability"})
PRODUCTION_INTENTS = Path(__file__).parent.parent.parent / "intent"


def _write_intent(
    directory: Path,
    *,
    name: str = "security.md",
    document_id: str = "security_intent",
    intent_text: str = "GitHub Actions uses OIDC.\n\nHuman-authored **context** stays here.",
    evaluation: str = "- Check: `github_actions_uses_oidc`",
    metadata: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    metadata_block = metadata or "\n".join(
        (
            "- Format: `1`",
            f"- Intent ID: `{document_id}`",
            "- Version: `1.0`",
            "- Category: `security`",
        )
    )
    evaluation_section = f"\n\n### Evaluation\n\n{evaluation}" if evaluation else ""
    path.write_text(
        (
            "# Security intent\n\n"
            f"{metadata_block}\n\n"
            "Free-form document context.\n\n"
            "## S-001 · CI credentials\n\n"
            "### Intent\n\n"
            f"{intent_text}"
            f"{evaluation_section}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_loads_free_text_markdown_as_a_deterministic_catalog(tmp_path: Path) -> None:
    first = tmp_path / "first"
    _write_intent(first, name="b.md")
    second = tmp_path / "second"
    _write_intent(second, name="a.md")

    first_catalog = load_intent_catalog(first, TAXONOMY)
    second_catalog = load_intent_catalog(second, TAXONOMY)

    assert first_catalog == second_catalog
    assert first_catalog.digest.startswith("intent-md-v1:")
    proposition = first_catalog.propositions[0]
    assert proposition.check_key == "github_actions_uses_oidc"
    assert proposition.priority is None
    assert proposition.statement.endswith("Human-authored **context** stays here.")


def test_unknown_check_is_data_for_an_unverified_outcome(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, evaluation="- Check: `future_deterministic_check`")

    proposition = load_intent_catalog(intent_dir, TAXONOMY).propositions[0]

    assert proposition.check_key == "future_deterministic_check"


def test_proposition_without_evaluation_metadata_remains_declared(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, evaluation="")

    proposition = load_intent_catalog(intent_dir, TAXONOMY).propositions[0]

    assert proposition.check_key is None
    assert proposition.statement.startswith("GitHub Actions")


def test_priority_can_be_declared_before_a_check_exists(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, evaluation="- Priority: `high`")

    proposition = load_intent_catalog(intent_dir, TAXONOMY).propositions[0]

    assert proposition.check_key is None
    assert proposition.priority == "high"


@pytest.mark.parametrize(
    ("evaluation", "message"),
    [
        ("- Check: `github_actions_uses_oidc`\n- Command: `run this`", "metadata is invalid"),
        (
            "- Check: `github_actions_uses_oidc`\n- Priority: `urgent`",
            "priority is not recognized",
        ),
        ("- Check: `../../command`", "safe identifier"),
    ],
)
def test_rejects_fields_outside_the_evaluation_contract(
    tmp_path: Path, evaluation: str, message: str
) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, evaluation=evaluation)

    with pytest.raises(PolicyError, match=message):
        load_intent_catalog(intent_dir, TAXONOMY)


def test_rejects_invalid_document_metadata(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(
        intent_dir,
        metadata="\n".join(
            (
                "- Format: `2`",
                "- Intent ID: `security_intent`",
                "- Version: `1.0`",
                "- Category: `security`",
            )
        ),
    )

    with pytest.raises(PolicyError, match="format must be 1"):
        load_intent_catalog(intent_dir, TAXONOMY)


def test_headings_inside_fenced_intent_text_are_not_structure(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(
        intent_dir,
        intent_text=(
            "An example remains prose:\n\n```markdown\n## Not a proposition\n### Evaluation\n```"
        ),
    )

    catalog = load_intent_catalog(intent_dir, TAXONOMY)

    assert len(catalog.propositions) == 1
    assert "## Not a proposition" in catalog.propositions[0].statement


def test_rejects_unsupported_proposition_sections(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(
        intent_dir,
        intent_text="Declared position.\n\n### Commands\n\nDo something.",
        evaluation="",
    )

    with pytest.raises(PolicyError, match="unsupported section"):
        load_intent_catalog(intent_dir, TAXONOMY)


def test_rejects_secret_like_free_text_without_echoing_it(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, intent_text="Credential: ghp_" + "a" * 36)

    with pytest.raises(PolicyError, match="secret-like value") as error:
        load_intent_catalog(intent_dir, TAXONOMY)

    assert "ghp_" not in str(error.value)


def test_rejects_duplicate_check_declarations_across_documents(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    _write_intent(intent_dir, name="first.md", document_id="first")
    _write_intent(intent_dir, name="second.md", document_id="second")

    with pytest.raises(PolicyError, match="check may be declared only once"):
        load_intent_catalog(intent_dir, TAXONOMY)


def test_rejects_symlinked_intent_documents(tmp_path: Path) -> None:
    intent_dir = tmp_path / "intent"
    target = _write_intent(tmp_path / "source")
    intent_dir.mkdir()
    (intent_dir / "linked.md").symlink_to(target)

    with pytest.raises(PolicyError, match="symbolic links"):
        load_intent_catalog(intent_dir, TAXONOMY)


def test_production_markdown_is_the_authoritative_catalog() -> None:
    catalog = load_intent_catalog(PRODUCTION_INTENTS, TAXONOMY)

    assert len(catalog.propositions) == 11
    assert {item.check_key for item in catalog.propositions if item.check_key is not None} == {
        "github_actions_uses_oidc",
        "persistent_iam_avoids_wildcards",
    }
    assert "Caveat:" in catalog.propositions[0].statement
