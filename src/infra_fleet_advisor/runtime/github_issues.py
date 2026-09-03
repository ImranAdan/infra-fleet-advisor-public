import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from infra_fleet_advisor.core.errors import IssuePublicationError
from infra_fleet_advisor.runtime.issue_publication import (
    FLEET_REPOSITORY,
    IssueAction,
    IssuePlan,
)

MAX_SEARCH_RESULTS = 100
COMMENTS_PER_PAGE = 100
MAX_COMMENT_PAGES = 10
_BOT_LOGIN = re.compile(r"^[A-Za-z0-9-]+\[bot\]$")


@dataclass(frozen=True, slots=True)
class RemoteIssue:
    number: int
    state: str
    author: str
    body: str
    is_pull_request: bool = False


@dataclass(frozen=True, slots=True)
class RemoteComment:
    author: str
    body: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    issues: tuple[RemoteIssue, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class CommentResult:
    comments: tuple[RemoteComment, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class PublicationResult:
    created: int = 0
    existing: int = 0
    labels_restored: int = 0
    resolution_comments: int = 0


class GitHubIssueClient(Protocol):
    def issues_with_label(self, label: str) -> tuple[RemoteIssue, ...]: ...

    def search_by_fingerprint(self, fingerprint: str) -> SearchResult: ...

    def ensure_label(self, name: str, color: str, description: str) -> None: ...

    def add_labels(self, issue_number: int, labels: tuple[str, ...]) -> None: ...

    def create_issue(self, title: str, body: str, labels: tuple[str, ...]) -> None: ...

    def comments(self, issue_number: int) -> CommentResult: ...

    def add_comment(self, issue_number: int, body: str) -> None: ...


def _body_has_exact_marker(body: str, marker: str) -> bool:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return marker in normalized.split("\n")


def _find_existing_issue(
    action: IssueAction,
    client: GitHubIssueClient,
    app_bot_login: str,
) -> tuple[RemoteIssue | None, bool]:
    labelled = client.issues_with_label(action.fingerprint_label)
    if len(labelled) > 1:
        raise IssuePublicationError("multiple records carry one fingerprint label")
    if labelled:
        issue = labelled[0]
        if issue.is_pull_request or issue.author.casefold() != app_bot_login.casefold():
            raise IssuePublicationError("fingerprint label belongs to a non-advisor record")
        if not _body_has_exact_marker(issue.body, action.fingerprint_marker):
            raise IssuePublicationError("fingerprint label and body marker disagree")
        return issue, False

    searched = client.search_by_fingerprint(action.fingerprint)
    if not searched.complete:
        raise IssuePublicationError("fingerprint body search was incomplete")
    advisor_matches = tuple(
        issue
        for issue in searched.issues
        if not issue.is_pull_request
        and issue.author.casefold() == app_bot_login.casefold()
        and _body_has_exact_marker(issue.body, action.fingerprint_marker)
    )
    if len(advisor_matches) > 1:
        raise IssuePublicationError("multiple advisor issues carry one fingerprint marker")
    return (advisor_matches[0], True) if advisor_matches else (None, False)


def _ensure_advisor_labels(client: GitHubIssueClient, fingerprint_label: str) -> None:
    client.ensure_label(
        "infra-fleet-advisor",
        "5319e7",
        "Evidence-backed recommendation published by Infra Fleet Advisor",
    )
    client.ensure_label(
        fingerprint_label,
        "b4a7d6",
        "Stable Infra Fleet Advisor recommendation fingerprint",
    )


def _publish_one(
    action: IssueAction,
    client: GitHubIssueClient,
    app_bot_login: str,
) -> PublicationResult:
    issue, found_by_body = _find_existing_issue(action, client, app_bot_login)
    labels_restored = 0
    if issue is not None and found_by_body:
        _ensure_advisor_labels(client, action.fingerprint_label)
        client.add_labels(issue.number, ("infra-fleet-advisor", action.fingerprint_label))
        labels_restored = 1

    if action.action == "active":
        if issue is not None:
            return PublicationResult(existing=1, labels_restored=labels_restored)
        _ensure_advisor_labels(client, action.fingerprint_label)
        client.create_issue(
            action.title,
            action.body,
            ("infra-fleet-advisor", action.fingerprint_label),
        )
        return PublicationResult(created=1)

    if action.action != "resolved":
        raise IssuePublicationError("issue plan contains an unknown action")
    if issue is None or issue.state != "open":
        return PublicationResult(
            existing=1 if issue is not None else 0,
            labels_restored=labels_restored,
        )

    comments = client.comments(issue.number)
    already_commented = any(
        comment.author.casefold() == app_bot_login.casefold()
        and _body_has_exact_marker(comment.body, action.resolution_marker)
        for comment in comments.comments
    )
    if already_commented:
        return PublicationResult(existing=1, labels_restored=labels_restored)
    if not comments.complete:
        raise IssuePublicationError("issue comments exceed the safe deduplication bound")
    client.add_comment(issue.number, action.resolution_comment)
    return PublicationResult(
        existing=1,
        labels_restored=labels_restored,
        resolution_comments=1,
    )


def publish_issue_plan(
    plan: IssuePlan,
    client: GitHubIssueClient,
    app_bot_login: str,
) -> PublicationResult:
    """Reconcile every plan item, collecting safe per-item failures until the end."""
    if plan.target_repository != FLEET_REPOSITORY:
        raise IssuePublicationError("issue plan targets an unsupported repository")
    if not _BOT_LOGIN.fullmatch(app_bot_login):
        raise IssuePublicationError("invalid GitHub App bot login")

    total = PublicationResult()
    failures = 0
    for action in plan.actions:
        try:
            result = _publish_one(action, client, app_bot_login)
        except IssuePublicationError:
            failures += 1
            continue
        total = PublicationResult(
            created=total.created + result.created,
            existing=total.existing + result.existing,
            labels_restored=total.labels_restored + result.labels_restored,
            resolution_comments=total.resolution_comments + result.resolution_comments,
        )
    if failures:
        raise IssuePublicationError(f"{failures} issue action(s) could not be safely published")
    return total


class GhCliIssueClient:
    """Narrow adapter over the preinstalled GitHub CLI; no shell is involved."""

    def __init__(self, repository: str) -> None:
        if not os.environ.get("GH_TOKEN"):
            raise IssuePublicationError("GH_TOKEN is required for issue publication")
        executable = shutil.which("gh")
        if executable is None:
            raise IssuePublicationError("GitHub CLI is required for issue publication")
        self._repository = repository
        self._executable = executable

    def _run(
        self,
        arguments: list[str],
        *,
        payload: dict[str, Any] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - resolved gh executable, argv only
                [self._executable, *arguments],
                input=json.dumps(payload) if payload is not None else None,
                text=True,
                capture_output=True,
                check=check,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise IssuePublicationError("GitHub API request failed") from exc

    def _api_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        arguments = ["api", "--method", method, endpoint]
        for key, value in (fields or {}).items():
            arguments += ["-f", f"{key}={value}"]
        if payload is not None:
            arguments += ["--input", "-"]
        result = self._run(arguments, payload=payload)
        try:
            return json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise IssuePublicationError("GitHub API returned malformed JSON") from exc

    @staticmethod
    def _issue(raw: Any) -> RemoteIssue:
        try:
            issue = RemoteIssue(
                number=int(raw["number"]),
                state=str(raw["state"]),
                author=str(raw["user"]["login"]),
                body=str(raw.get("body") or ""),
                is_pull_request="pull_request" in raw,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IssuePublicationError("GitHub returned a malformed issue") from exc
        if issue.number < 1 or issue.state not in ("open", "closed"):
            raise IssuePublicationError("GitHub returned an invalid issue identity")
        return issue

    def issues_with_label(self, label: str) -> tuple[RemoteIssue, ...]:
        raw = self._api_json(
            f"repos/{self._repository}/issues",
            fields={"state": "all", "labels": label, "per_page": "2"},
        )
        if not isinstance(raw, list):
            raise IssuePublicationError("GitHub returned a malformed issue list")
        return tuple(self._issue(item) for item in raw)

    def search_by_fingerprint(self, fingerprint: str) -> SearchResult:
        query = (
            f"repo:{self._repository} is:issue in:body "
            f'"infra-fleet-advisor-fingerprint: {fingerprint}"'
        )
        raw = self._api_json(
            "search/issues", fields={"q": query, "per_page": str(MAX_SEARCH_RESULTS)}
        )
        try:
            items = raw["items"]
            complete = not bool(raw["incomplete_results"]) and int(raw["total_count"]) <= len(items)
        except (KeyError, TypeError, ValueError) as exc:
            raise IssuePublicationError("GitHub returned a malformed issue search") from exc
        if not isinstance(items, list):
            raise IssuePublicationError("GitHub returned malformed issue search items")
        return SearchResult(tuple(self._issue(item) for item in items), complete)

    def ensure_label(self, name: str, color: str, description: str) -> None:
        encoded = quote(name, safe="")
        lookup = self._run(["api", f"repos/{self._repository}/labels/{encoded}"], check=False)
        if lookup.returncode == 0:
            return
        if "HTTP 404" not in lookup.stderr:
            raise IssuePublicationError("GitHub label lookup failed")
        create = self._run(
            [
                "api",
                "--method",
                "POST",
                f"repos/{self._repository}/labels",
                "--input",
                "-",
            ],
            payload={"name": name, "color": color, "description": description},
            check=False,
        )
        if create.returncode == 0:
            return
        # A concurrent retry may create the label between GET and POST. Accept
        # 422 only after a second successful lookup proves the desired label exists.
        if "HTTP 422" in create.stderr:
            verify = self._run(["api", f"repos/{self._repository}/labels/{encoded}"], check=False)
            if verify.returncode == 0:
                return
        raise IssuePublicationError("GitHub label creation failed")

    def add_labels(self, issue_number: int, labels: tuple[str, ...]) -> None:
        self._api_json(
            f"repos/{self._repository}/issues/{issue_number}/labels",
            method="POST",
            payload={"labels": list(labels)},
        )

    def create_issue(self, title: str, body: str, labels: tuple[str, ...]) -> None:
        self._api_json(
            f"repos/{self._repository}/issues",
            method="POST",
            payload={"title": title, "body": body, "labels": list(labels)},
        )

    def comments(self, issue_number: int) -> CommentResult:
        comments: list[RemoteComment] = []
        for page in range(1, MAX_COMMENT_PAGES + 1):
            raw = self._api_json(
                f"repos/{self._repository}/issues/{issue_number}/comments",
                fields={"per_page": str(COMMENTS_PER_PAGE), "page": str(page)},
            )
            if not isinstance(raw, list):
                raise IssuePublicationError("GitHub returned a malformed comment list")
            try:
                for item in raw:
                    comments.append(
                        RemoteComment(
                            author=str(item["user"]["login"]),
                            body=str(item.get("body") or ""),
                        )
                    )
            except (KeyError, TypeError) as exc:
                raise IssuePublicationError("GitHub returned a malformed comment") from exc
            if len(raw) < COMMENTS_PER_PAGE:
                return CommentResult(tuple(comments), complete=True)
        return CommentResult(tuple(comments), complete=False)

    def add_comment(self, issue_number: int, body: str) -> None:
        self._api_json(
            f"repos/{self._repository}/issues/{issue_number}/comments",
            method="POST",
            payload={"body": body},
        )
