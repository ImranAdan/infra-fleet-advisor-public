import json
from copy import deepcopy
from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.runtime.report_signature import (
    MAX_ADVISORY_PR_HISTORY,
    MAX_DECLINED_PR_BODY_BYTES,
    body_records_decline,
    compute_report_signature,
    decide_publication,
    decline_marker,
    read_declined_pr_body,
    read_latest_declined_pr_body,
)


def _report() -> dict[str, object]:
    return {
        "provenance": {
            "policy_version": "1.0",
            "run_started_at": "2026-09-01T00:00:00Z",
        },
        "recommendations": [
            {
                "fingerprint": "fp_b",
                "status": "new",
                "owner_accepted_trade_off": None,
                "title": "model-authored title",
                "rank": 1,
            },
            {
                "fingerprint": "fp_a",
                "status": "resolved",
                "owner_accepted_trade_off": "accepted for now",
                "title": "another title",
                "rank": None,
            },
        ],
        "evidence": [
            {
                "evidence_id": "ev_b",
                "kind": "kind_b",
                "source_path": "b.tf",
                "locator": "resource.b",
                "fact": {"enabled": True},
                "excerpt": "bounded fact b",
            },
            {
                "evidence_id": "ev_a",
                "kind": "kind_a",
                "source_path": "a.tf",
                "locator": "resource.a",
                "fact": {"value": "x"},
                "excerpt": "bounded fact a",
            },
        ],
        "coverage": [
            {
                "collector_id": "collector_b",
                "status": "ok",
                "evidence_count": 1,
                "error_summary": None,
            },
            {
                "collector_id": "collector_a",
                "status": "partial",
                "evidence_count": 2,
                "error_summary": "one file omitted",
            },
        ],
        "rejected": [{"concern_key": "ignored", "reason": "invalid_priority"}],
    }


def _write(tmp_path: Path, payload: dict[str, object], name: str = "report.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_signature_ignores_narrative_provenance_rank_and_open_lifecycle(tmp_path: Path) -> None:
    original = _report()
    changed = deepcopy(original)
    provenance = changed["provenance"]
    assert isinstance(provenance, dict)
    provenance["run_started_at"] = "2026-09-02T00:00:00Z"
    recommendations = changed["recommendations"]
    assert isinstance(recommendations, list)
    first = recommendations[0]
    assert isinstance(first, dict)
    first["title"] = "rewritten by another model"
    first["rank"] = 99
    first["status"] = "unchanged"

    assert compute_report_signature(_write(tmp_path, original, "original.json")) == (
        compute_report_signature(_write(tmp_path, changed, "changed.json"))
    )


def test_signature_changes_with_policy_version(tmp_path: Path) -> None:
    original = _report()
    changed = deepcopy(original)
    provenance = changed["provenance"]
    assert isinstance(provenance, dict)
    provenance["policy_version"] = "2.0"

    assert compute_report_signature(_write(tmp_path, original, "original.json")) != (
        compute_report_signature(_write(tmp_path, changed, "changed.json"))
    )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("recommendations", "owner_accepted_trade_off", "new decision"),
        ("evidence", "excerpt", "different deterministic fact"),
        ("evidence", "source_path", "moved/file.tf"),
        ("evidence", "locator", "resource.moved"),
        ("coverage", "status", "failed"),
        ("coverage", "evidence_count", 5),
        ("coverage", "error_summary", "different omission"),
        ("rejected", "reason", "invented_evidence_id"),
    ],
)
def test_signature_changes_with_material_report_content(
    tmp_path: Path, section: str, field: str, value: str | int
) -> None:
    original = _report()
    changed = deepcopy(original)
    records = changed[section]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    first[field] = value

    assert compute_report_signature(_write(tmp_path, original, "original.json")) != (
        compute_report_signature(_write(tmp_path, changed, "changed.json"))
    )


def test_signature_is_independent_of_report_order(tmp_path: Path) -> None:
    original = _report()
    reordered = deepcopy(original)
    for section in ("recommendations", "evidence", "coverage"):
        records = reordered[section]
        assert isinstance(records, list)
        records.reverse()

    assert compute_report_signature(_write(tmp_path, original, "original.json")) == (
        compute_report_signature(_write(tmp_path, reordered, "reordered.json"))
    )


def test_signature_rejects_malformed_material_fields(tmp_path: Path) -> None:
    malformed = _report()
    malformed["coverage"] = "not a list"

    with pytest.raises(PolicyError, match="cannot compute report signature"):
        compute_report_signature(_write(tmp_path, malformed))


def test_decline_requires_an_exact_versioned_marker(tmp_path: Path) -> None:
    signature = compute_report_signature(_write(tmp_path, _report()))
    marker = decline_marker(signature)

    assert body_records_decline(f"review\n{marker}\nreport", signature)
    assert not body_records_decline(f"review {marker} report", signature)
    assert not body_records_decline(
        "<!-- infra-fleet-advisor-report-signature: v1:" + "0" * 64 + " -->",
        signature,
    )
    assert not body_records_decline(f"prose\u2028{marker}", signature)


def test_decline_marker_rejects_arbitrary_input() -> None:
    with pytest.raises(ValueError, match="invalid report signature"):
        decline_marker("$(untrusted)")


def test_declined_pr_body_reader_is_bounded(tmp_path: Path) -> None:
    body = tmp_path / "body.txt"
    body.write_text("x" * (MAX_DECLINED_PR_BODY_BYTES + 1), encoding="utf-8")

    with pytest.raises(PolicyError, match="declined pull request body exceeds"):
        read_declined_pr_body(body)


def _closed_pull_request(
    number: int,
    *,
    author: str = "github-actions[bot]",
    merged: bool = False,
    body: str = "declined marker",
) -> dict[str, object]:
    return {
        "number": number,
        "state": "closed",
        "user": {"login": author},
        "body": body,
        "merged_at": "2026-09-01T00:00:00Z" if merged else None,
        "head": {
            "ref": "advisory/latest",
            "repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"},
        },
        "base": {"repo": {"full_name": "ImranAdan/infra-fleet-advisor-public"}},
    }


def test_latest_decline_ignores_newer_human_pull_request(tmp_path: Path) -> None:
    history = tmp_path / "pulls.json"
    history.write_text(
        json.dumps(
            [
                _closed_pull_request(12, author="maintainer", body="human closure"),
                _closed_pull_request(11, body="workflow decline"),
            ]
        ),
        encoding="utf-8",
    )

    assert (
        read_latest_declined_pr_body(
            history,
            repository="ImranAdan/infra-fleet-advisor-public",
            branch="advisory/latest",
        )
        == "workflow decline"
    )


def test_latest_workflow_merge_supersedes_an_older_decline(tmp_path: Path) -> None:
    history = tmp_path / "pulls.json"
    history.write_text(
        json.dumps(
            [
                _closed_pull_request(12, merged=True, body="accepted"),
                _closed_pull_request(11, body="workflow decline"),
            ]
        ),
        encoding="utf-8",
    )

    assert (
        read_latest_declined_pr_body(
            history,
            repository="ImranAdan/infra-fleet-advisor-public",
            branch="advisory/latest",
        )
        == ""
    )


def test_advisory_pull_request_history_is_bounded_and_source_checked(tmp_path: Path) -> None:
    history = tmp_path / "pulls.json"
    history.write_text(
        json.dumps([_closed_pull_request(number) for number in range(1, 202)]),
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="history failed validation"):
        read_latest_declined_pr_body(
            history,
            repository="ImranAdan/infra-fleet-advisor-public",
            branch="advisory/latest",
        )

    wrong_source = _closed_pull_request(MAX_ADVISORY_PR_HISTORY)
    head = wrong_source["head"]
    assert isinstance(head, dict)
    head["repo"] = {"full_name": "attacker/fork"}
    history.write_text(json.dumps([wrong_source]), encoding="utf-8")
    with pytest.raises(PolicyError, match="history failed validation"):
        read_latest_declined_pr_body(
            history,
            repository="ImranAdan/infra-fleet-advisor-public",
            branch="advisory/latest",
        )


def test_publication_decision_is_unchanged_against_accepted_report(tmp_path: Path) -> None:
    report = _write(tmp_path, _report())

    decision = decide_publication(
        report,
        prior_report=report,
        latest_declined_pr_body=decline_marker(compute_report_signature(report)),
    )

    assert decision.decision == "unchanged"


def test_publication_decision_honors_latest_closed_pr_marker(tmp_path: Path) -> None:
    current = _write(tmp_path, _report(), "current.json")
    prior_payload = _report()
    evidence = prior_payload["evidence"]
    assert isinstance(evidence, list)
    first = evidence[0]
    assert isinstance(first, dict)
    first["excerpt"] = "old evidence"
    prior = _write(tmp_path, prior_payload, "prior.json")
    signature = compute_report_signature(current)

    decision = decide_publication(
        current,
        prior_report=prior,
        latest_declined_pr_body=f"prose\n{decline_marker(signature)}\nmore prose",
    )

    assert decision.decision == "declined"
    assert decision.signature == signature
    assert decision.marker == decline_marker(signature)


def test_publication_decision_reports_material_change(tmp_path: Path) -> None:
    current = _write(tmp_path, _report(), "current.json")
    prior_payload = _report()
    prior_payload["coverage"] = []
    prior = _write(tmp_path, prior_payload, "prior.json")

    decision = decide_publication(
        current,
        prior_report=prior,
        latest_declined_pr_body="untrusted prose without an exact marker",
    )

    assert decision.decision == "changed"
