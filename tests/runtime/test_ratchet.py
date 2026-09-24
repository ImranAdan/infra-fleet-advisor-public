import json
from pathlib import Path

from infra_fleet_advisor.runtime.cli import EXIT_OK, EXIT_RATCHET_SLIPPED, main
from infra_fleet_advisor.runtime.ratchet import compare_advisors, to_markdown

CHECK = "some_check"


def _report(path: Path, positions: dict[str, tuple[str, str | None]]) -> Path:
    evaluations = [
        {"document_id": "cost", "proposition_id": key, "status": status,
         "statement": f"Position {key}", "check_key": check, "evidence_ids": []}
        for key, (status, check) in positions.items()
    ]  # fmt: skip
    path.write_text(json.dumps({"intent_evaluations": evaluations}), encoding="utf-8")
    return path


def test_every_move_is_classified(tmp_path: Path) -> None:
    base = _report(
        tmp_path / "base.json",
        {
            "A": ("satisfied", CHECK),  # loses its result
            "B": ("divergent", CHECK),  # loses its check
            "C": ("divergent", CHECK),  # finding vanishes
            "D": ("declared_unverified", None),  # gains proof
            "E": ("declared_unverified", None),  # gains a finding
            "F": ("satisfied", CHECK),  # removed from the catalog
            "G": ("divergent", CHECK),  # unchanged
        },
    )
    head = _report(
        tmp_path / "head.json",
        {
            "A": ("declared_unverified", CHECK),
            "B": ("declared_unverified", None),
            "C": ("satisfied", CHECK),
            "D": ("satisfied", CHECK),
            "E": ("divergent", CHECK),
            "G": ("divergent", CHECK),
            "H": ("satisfied", CHECK),  # new position, proven at once
        },
    )

    result = compare_advisors(base, head)

    keys = lambda items: [p.key for p in items]  # noqa: E731
    assert keys(result.lost_proof) == ["cost/A"]
    assert keys(result.lost_checks) == ["cost/B", "cost/F"]
    assert keys(result.vanished_findings) == ["cost/C"]
    assert keys(result.new_proof) == ["cost/D", "cost/H"]
    assert keys(result.new_findings) == ["cost/E"]
    assert result.base_score == (5, 2, 3)
    assert result.head_score == (6, 3, 2)
    assert not result.passed
    assert "Ratchet guard slipped" in to_markdown(result)


def test_gaining_proof_and_findings_holds(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", {"A": ("declared_unverified", None)})
    head = _report(tmp_path / "head.json", {"A": ("divergent", CHECK)})

    result = compare_advisors(base, head)

    assert result.passed
    assert "Ratchet guard holds" in to_markdown(result)


def test_ratchet_cli_exit_code_is_the_verdict(tmp_path: Path) -> None:
    base = _report(tmp_path / "base.json", {"A": ("satisfied", CHECK)})
    slipped = _report(tmp_path / "head.json", {"A": ("declared_unverified", CHECK)})
    summary = tmp_path / "summary.md"
    argv = ["ratchet", "--base-report", str(base), "--head-report"]

    assert main([*argv, str(base)]) == EXIT_OK
    assert main([*argv, str(slipped), "--summary", str(summary)]) == EXIT_RATCHET_SLIPPED
    assert "Lost proof" in summary.read_text(encoding="utf-8")
