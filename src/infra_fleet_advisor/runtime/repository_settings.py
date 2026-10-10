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

from infra_fleet_advisor.scenarios.fleet_repository_review.collectors.repository_settings_collector import (  # noqa: E501
    SNAPSHOT_SCHEMA,
)

API_ROOT = "https://api.github.com"
_TIMEOUT_SECONDS = 10

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
            return int(response.status), response.read(4096)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def fetch_settings(
    repository: str, token: str | None, fetched_at: str, opener: Opener = urllib.request.urlopen
) -> dict[str, object]:
    """Return a snapshot dict; values are None when they cannot be known."""
    snapshot: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "repository": repository,
        "fetched_at": fetched_at,
        "dependabot_alerts": None,
        "security_updates": None,
        "reason": "",
    }
    if not token:
        snapshot["reason"] = "no settings token was provided"
        return snapshot
    base = f"{API_ROOT}/repos/{repository}"
    # Only a token with Administration: read gets 200 here, which also makes
    # the 204/404 below a real answer rather than a permission error.
    status, body = _get(f"{base}/automated-security-fixes", token, opener)
    if status != 200:
        snapshot["reason"] = f"automated-security-fixes returned HTTP {status}"
        return snapshot
    try:
        enabled = json.loads(body).get("enabled")
    except (ValueError, AttributeError):
        enabled = None
    if not isinstance(enabled, bool):
        snapshot["reason"] = "automated-security-fixes response was malformed"
        return snapshot
    status, _ = _get(f"{base}/vulnerability-alerts", token, opener)
    alerts = {204: True, 404: False}.get(status)
    if alerts is None:
        snapshot["reason"] = f"vulnerability-alerts returned HTTP {status}"
        return snapshot
    snapshot["dependabot_alerts"] = alerts
    snapshot["security_updates"] = enabled
    return snapshot


def write_snapshot(snapshot: dict[str, object], output: Path) -> None:
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
