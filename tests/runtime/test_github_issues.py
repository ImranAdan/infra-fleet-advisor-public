import json
import subprocess
from typing import Literal

import pytest

from infra_fleet_advisor.core.errors import IssuePublicationError
from infra_fleet_advisor.runtime.github_issues import (
    CommentResult,
    GhCliIssueClient,
    PublicationResult,
    RemoteComment,
    RemoteIssue,
    SearchResult,
    publish_issue_plan,
)
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_REPOSITORY,
    IssueAction,
    IssuePlan,
)

BOT = "infra-fleet-advisor[bot]"


def _action(
    digest: str,
    *,
    action: Literal["active", "resolved"] = "active",
    source_sha: str = "a" * 40,
) -> IssueAction:
    fingerprint = f"fp_{digest}"
    fingerprint_marker = f"<!-- infra-fleet-advisor-fingerprint: {fingerprint} -->"
    resolution_marker = f"<!-- infra-fleet-advisor-resolution: {fingerprint} -->"
    return IssueAction(
        action=action,
        fingerprint=fingerprint,
        fingerprint_label=f"advisor:fp:{digest}",
        fingerprint_marker=fingerprint_marker,
        title="[Advisor][medium] Test finding",
        body=f"{fingerprint_marker}\n\nEvidence-backed body.",
        resolution_marker=resolution_marker,
        resolution_comment=f"{resolution_marker}\n\nNo longer detected at {source_sha}.",
    )


def _plan(*actions: IssueAction, repository: str = FLEET_REPOSITORY) -> IssuePlan:
    return IssuePlan(repository, "a" * 40, actions)


class FakeIssueClient:
    def __init__(self) -> None:
        self.issues: dict[int, RemoteIssue] = {}
        self.issue_labels: dict[int, set[str]] = {}
        self.issue_comments: dict[int, list[RemoteComment]] = {}
        self.labels: set[str] = set()
        self.incomplete_searches: set[str] = set()
        self.incomplete_comments: set[int] = set()
        self.next_number = 1

    def issues_with_label(self, label: str) -> tuple[RemoteIssue, ...]:
        return tuple(
            issue
            for number, issue in self.issues.items()
            if label in self.issue_labels.get(number, set())
        )

    def search_by_fingerprint(self, fingerprint: str) -> SearchResult:
        return SearchResult(
            tuple(issue for issue in self.issues.values() if fingerprint in issue.body),
            fingerprint not in self.incomplete_searches,
        )

    def ensure_label(self, name: str, color: str, description: str) -> None:
        assert color
        assert description
        self.labels.add(name)

    def add_labels(self, issue_number: int, labels: tuple[str, ...]) -> None:
        self.issue_labels.setdefault(issue_number, set()).update(labels)

    def create_issue(self, title: str, body: str, labels: tuple[str, ...]) -> None:
        number = self.next_number
        self.next_number += 1
        self.issues[number] = RemoteIssue(number, "open", BOT, body)
        self.issue_labels[number] = set(labels)
        self.issue_comments[number] = []
        assert title

    def comments(self, issue_number: int) -> CommentResult:
        return CommentResult(
            tuple(self.issue_comments.get(issue_number, [])),
            issue_number not in self.incomplete_comments,
        )

    def add_comment(self, issue_number: int, body: str) -> None:
        self.issue_comments.setdefault(issue_number, []).append(RemoteComment(BOT, body))

    def add_existing(
        self,
        action: IssueAction,
        *,
        state: str = "open",
        author: str = BOT,
        labelled: bool = True,
        body: str | None = None,
        is_pull_request: bool = False,
    ) -> int:
        number = self.next_number
        self.next_number += 1
        self.issues[number] = RemoteIssue(
            number,
            state,
            author,
            body if body is not None else action.body,
            is_pull_request,
        )
        self.issue_labels[number] = {action.fingerprint_label} if labelled else set()
        self.issue_comments[number] = []
        return number


def test_active_publication_is_idempotent_per_fingerprint() -> None:
    client = FakeIssueClient()
    action = _action("1" * 24)

    first = publish_issue_plan(_plan(action), client, BOT)
    second = publish_issue_plan(_plan(action), client, BOT)

    assert first == PublicationResult(created=1)
    assert second == PublicationResult(existing=1)
    assert len(client.issues) == 1


def test_body_marker_recovers_labels_without_creating_a_duplicate() -> None:
    client = FakeIssueClient()
    action = _action("2" * 24)
    issue_number = client.add_existing(action, labelled=False)

    result = publish_issue_plan(_plan(action), client, BOT)

    assert result == PublicationResult(existing=1, labels_restored=1)
    assert action.fingerprint_label in client.issue_labels[issue_number]
    assert "infra-fleet-advisor" in client.issue_labels[issue_number]
    assert len(client.issues) == 1


def test_resolution_comment_is_once_per_fingerprint_across_source_commits() -> None:
    client = FakeIssueClient()
    first = _action("3" * 24, action="resolved", source_sha="a" * 40)
    later = _action("3" * 24, action="resolved", source_sha="b" * 40)
    issue_number = client.add_existing(first)

    first_result = publish_issue_plan(_plan(first), client, BOT)
    second_result = publish_issue_plan(_plan(later), client, BOT)

    assert first_result.resolution_comments == 1
    assert second_result.resolution_comments == 0
    assert len(client.issue_comments[issue_number]) == 1


def test_closed_issue_is_never_reopened_or_commented() -> None:
    client = FakeIssueClient()
    action = _action("4" * 24, action="resolved")
    issue_number = client.add_existing(action, state="closed")

    result = publish_issue_plan(_plan(action), client, BOT)

    assert result == PublicationResult(existing=1)
    assert client.issues[issue_number].state == "closed"
    assert client.issue_comments[issue_number] == []


def test_crlf_markers_are_recognized() -> None:
    client = FakeIssueClient()
    action = _action("5" * 24)
    body = action.body.replace("\n", "\r\n")
    client.add_existing(action, body=body)

    assert publish_issue_plan(_plan(action), client, BOT) == PublicationResult(existing=1)


def test_bot_login_comparison_is_case_insensitive() -> None:
    client = FakeIssueClient()
    action = _action("c" * 24)
    client.add_existing(action, author=BOT.upper())

    assert publish_issue_plan(_plan(action), client, BOT) == PublicationResult(existing=1)


def test_permanent_collision_does_not_block_later_fingerprints() -> None:
    client = FakeIssueClient()
    poisoned = _action("6" * 24)
    publishable = _action("7" * 24)
    client.add_existing(poisoned, author="someone-else")

    with pytest.raises(IssuePublicationError, match="1 issue action"):
        publish_issue_plan(_plan(poisoned, publishable), client, BOT)

    assert any(publishable.fingerprint_marker in issue.body for issue in client.issues.values())


def test_incomplete_comment_history_fails_instead_of_duplicating() -> None:
    client = FakeIssueClient()
    action = _action("8" * 24, action="resolved")
    issue_number = client.add_existing(action)
    client.incomplete_comments.add(issue_number)

    with pytest.raises(IssuePublicationError, match="1 issue action"):
        publish_issue_plan(_plan(action), client, BOT)

    assert client.issue_comments[issue_number] == []


def test_incomplete_body_search_fails_instead_of_creating() -> None:
    client = FakeIssueClient()
    action = _action("d" * 24)
    client.incomplete_searches.add(action.fingerprint)

    with pytest.raises(IssuePublicationError, match="1 issue action"):
        publish_issue_plan(_plan(action), client, BOT)

    assert client.issues == {}


def test_only_exact_bot_authored_resolution_marker_deduplicates() -> None:
    client = FakeIssueClient()
    action = _action("9" * 24, action="resolved")
    issue_number = client.add_existing(action)
    client.issue_comments[issue_number] = [
        RemoteComment("someone-else", action.resolution_marker),
        RemoteComment(BOT, f"prose {action.resolution_marker}"),
    ]

    result = publish_issue_plan(_plan(action), client, BOT)

    assert result.resolution_comments == 1
    assert len(client.issue_comments[issue_number]) == 3


def test_wrong_repository_and_invalid_bot_identity_fail_before_writes() -> None:
    action = _action("a" * 24)
    client = FakeIssueClient()

    with pytest.raises(IssuePublicationError, match="unsupported repository"):
        publish_issue_plan(_plan(action, repository="someone/else"), client, BOT)
    with pytest.raises(IssuePublicationError, match="invalid GitHub App bot login"):
        publish_issue_plan(_plan(action), client, "not-a-bot")

    assert client.issues == {}


def test_pull_request_with_fingerprint_label_is_rejected() -> None:
    client = FakeIssueClient()
    action = _action("e" * 24)
    client.add_existing(action, is_pull_request=True)

    with pytest.raises(IssuePublicationError, match="1 issue action"):
        publish_issue_plan(_plan(action), client, BOT)


def test_active_finding_does_not_reopen_or_duplicate_a_closed_issue() -> None:
    client = FakeIssueClient()
    action = _action("f" * 24)
    issue_number = client.add_existing(action, state="closed")

    assert publish_issue_plan(_plan(action), client, BOT) == PublicationResult(existing=1)
    assert client.issues[issue_number].state == "closed"
    assert len(client.issues) == 1


def test_mismatched_body_marker_fails_loudly() -> None:
    client = FakeIssueClient()
    action = _action("b" * 24)
    client.add_existing(action, body="<!-- wrong marker -->")

    with pytest.raises(IssuePublicationError, match="1 issue action"):
        publish_issue_plan(_plan(action), client, BOT)


def _adapter() -> GhCliIssueClient:
    client = object.__new__(GhCliIssueClient)
    client._repository = FLEET_REPOSITORY
    client._executable = "/usr/bin/gh"
    return client


def test_gh_adapter_paginates_comments_to_a_bounded_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _adapter()
    requested_pages: list[str] = []

    def fake_api(endpoint, *, method="GET", fields=None, payload=None):
        assert endpoint.endswith("/comments")
        assert method == "GET"
        assert payload is None
        page = fields["page"]
        requested_pages.append(page)
        count = 100 if page == "1" else 1
        return [{"user": {"login": BOT}, "body": f"comment-{index}"} for index in range(count)]

    monkeypatch.setattr(client, "_api_json", fake_api)

    result = client.comments(7)

    assert result.complete
    assert len(result.comments) == 101
    assert requested_pages == ["1", "2"]


def test_gh_adapter_does_not_treat_non_404_label_error_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _adapter()
    calls = 0

    def fake_run(arguments, *, payload=None, check=True):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(arguments, 1, "", "gh: rate limited (HTTP 403)")

    monkeypatch.setattr(client, "_run", fake_run)

    with pytest.raises(IssuePublicationError, match="label lookup failed"):
        client.ensure_label("label", "ffffff", "description")

    assert calls == 1


def test_gh_adapter_creates_only_after_a_404_label_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _adapter()
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(arguments, *, payload=None, check=True):
        calls.append((arguments, payload))
        if len(calls) == 1:
            return subprocess.CompletedProcess(arguments, 1, "", "gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(arguments, 0, "{}", "")

    monkeypatch.setattr(client, "_run", fake_run)

    client.ensure_label("advisor:fp:value", "ffffff", "description")

    assert len(calls) == 2
    assert calls[1][1] == {
        "name": "advisor:fp:value",
        "color": "ffffff",
        "description": "description",
    }


def test_gh_adapter_sends_issue_body_as_json_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _adapter()
    captured: dict[str, object] = {}

    def fake_run(arguments, *, payload=None, check=True):
        captured["arguments"] = arguments
        captured["payload"] = payload
        return subprocess.CompletedProcess(arguments, 0, json.dumps({"number": 1}), "")

    monkeypatch.setattr(client, "_run", fake_run)

    client.create_issue("title", "body with $(inert)", ("label",))

    assert "--input" in captured["arguments"]
    assert captured["payload"] == {
        "title": "title",
        "body": "body with $(inert)",
        "labels": ["label"],
    }
