"""Fetch a repository's security-and-analysis settings into a snapshot (PDR 0009).

The advisor's one live read. It runs before a review, never inside one, so
the review stays offline and deterministic over its inputs. Both endpoints
need a token with Administration: read; without one the snapshot records
unknown values and the collector reports partial coverage."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.repository_settings_collector import (  # noqa: E501
    SETTING_KEYS,
    SNAPSHOT_SCHEMA,
)

API_ROOT = "https://api.github.com"
_TIMEOUT_SECONDS = 10
_MAX_BODY_BYTES = 64 * 1024

Opener = Callable[..., Any]


def _get(url: str, token: str, opener: Opener) -> tuple[int, bytes]:
    # url is always API_ROOT (fixed https) plus a fixed path.
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read(_MAX_BODY_BYTES)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def _json(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _status_enabled(security: dict[str, Any], key: str) -> bool | None:
    entry = security.get(key)
    status = entry.get("status") if isinstance(entry, dict) else None
    return {"enabled": True, "disabled": False}.get(status) if isinstance(status, str) else None


def _protected(protection: dict[str, Any]) -> bool:
    """Pull requests required, and neither force-push nor deletion allowed."""

    def enabled(key: str) -> bool:
        entry = protection.get(key)
        return isinstance(entry, dict) and entry.get("enabled") is True

    return (
        isinstance(protection.get("required_pull_request_reviews"), dict)
        and not enabled("allow_force_pushes")
        and not enabled("allow_deletions")
    )


def fetch_settings(
    repository: str, token: str | None, fetched_at: str, opener: Opener = urllib.request.urlopen
) -> dict[str, object]:
    """Return a snapshot dict; values are None when they cannot be known."""
    snapshot: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "repository": repository,
        "fetched_at": fetched_at,
        "reason": "",
        **dict.fromkeys(SETTING_KEYS),
    }
    if not token:
        snapshot["reason"] = "no settings token was provided"
        return snapshot
    base = f"{API_ROOT}/repos/{repository}"
    # Only a token with Administration: read gets 200 here, which also makes
    # the 404s below real answers ("off", "unprotected") rather than
    # permission errors.
    status, body = _get(f"{base}/automated-security-fixes", token, opener)
    if status != 200:
        snapshot["reason"] = f"automated-security-fixes returned HTTP {status}"
        return snapshot
    enabled = _json(body).get("enabled")
    if not isinstance(enabled, bool):
        snapshot["reason"] = "automated-security-fixes response was malformed"
        return snapshot
    snapshot["security_updates"] = enabled
    reasons = []

    status, _ = _get(f"{base}/vulnerability-alerts", token, opener)
    snapshot["dependabot_alerts"] = {204: True, 404: False}.get(status)
    if snapshot["dependabot_alerts"] is None:
        reasons.append(f"vulnerability-alerts returned HTTP {status}")

    status, body = _get(base, token, opener)
    repo = _json(body) if status == 200 else {}
    security = repo.get("security_and_analysis")
    security = security if isinstance(security, dict) else {}
    snapshot["secret_scanning"] = _status_enabled(security, "secret_scanning")
    snapshot["push_protection"] = _status_enabled(security, "secret_scanning_push_protection")
    if snapshot["secret_scanning"] is None or snapshot["push_protection"] is None:
        reasons.append(f"security_and_analysis unavailable (HTTP {status})")

    branch = repo.get("default_branch")
    if isinstance(branch, str) and branch:
        status, body = _get(f"{base}/branches/{quote(branch, safe='')}/protection", token, opener)
        snapshot["default_branch_protected"] = (
            _protected(_json(body)) if status == 200 else False if status == 404 else None
        )
        if snapshot["default_branch_protected"] is None:
            reasons.append(f"branch protection returned HTTP {status}")
    else:
        reasons.append("default branch unknown")
    snapshot["reason"] = "; ".join(reasons)
    return snapshot


def write_snapshot(snapshot: dict[str, object], output: Path) -> None:
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
