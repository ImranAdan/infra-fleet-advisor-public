import io
import json
import urllib.error

from infra_fleet_advisor.runtime.repository_settings import fetch_settings


class _Response(io.BytesIO):
    def __init__(self, status: int, body: bytes = b"") -> None:
        super().__init__(body)
        self.status = status


def _opener(answers: dict[str, tuple[int, bytes]]):
    seen: list[str] = []

    def opener(request, timeout):  # type: ignore[no-untyped-def]
        endpoint = request.full_url.rsplit("/", 1)[-1]
        seen.append(endpoint)
        assert request.get_header("Authorization") == "Bearer t0ken"
        status, body = answers[endpoint]
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)
        return _Response(status, body)

    opener.seen = seen  # type: ignore[attr-defined]
    return opener


def _fetch(answers: dict[str, tuple[int, bytes]]):
    return fetch_settings("ImranAdan/infra-fleet-public", "t0ken", "T", opener=_opener(answers))


def test_reads_both_settings_with_an_administration_token() -> None:
    snapshot = _fetch(
        {
            "automated-security-fixes": (200, json.dumps({"enabled": True}).encode()),
            "vulnerability-alerts": (204, b""),
        }
    )
    assert snapshot["dependabot_alerts"] is True
    assert snapshot["security_updates"] is True
    assert snapshot["reason"] == ""


def test_alerts_404_after_a_permitted_call_means_off() -> None:
    snapshot = _fetch(
        {
            "automated-security-fixes": (200, json.dumps({"enabled": False}).encode()),
            "vulnerability-alerts": (404, b""),
        }
    )
    assert snapshot["dependabot_alerts"] is False
    assert snapshot["security_updates"] is False


def test_without_permission_both_values_stay_unknown() -> None:
    snapshot = _fetch({"automated-security-fixes": (403, b"")})
    assert snapshot["dependabot_alerts"] is None
    assert snapshot["security_updates"] is None
    assert snapshot["reason"] == "automated-security-fixes returned HTTP 403"


def test_no_token_makes_no_request() -> None:
    snapshot = fetch_settings(
        "ImranAdan/infra-fleet-public", None, "T", opener=lambda *a, **k: 1 / 0
    )
    assert snapshot["reason"] == "no settings token was provided"
    assert snapshot["dependabot_alerts"] is None


def test_malformed_fix_status_is_unknown() -> None:
    snapshot = _fetch({"automated-security-fixes": (200, b"not json")})
    assert snapshot["security_updates"] is None
    assert snapshot["reason"] == "automated-security-fixes response was malformed"
