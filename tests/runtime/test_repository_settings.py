import io
import json
import urllib.error

from infra_fleet_advisor.runtime.repository_settings import fetch_settings

REPO = {
    "default_branch": "main",
    "security_and_analysis": {
        "secret_scanning": {"status": "enabled"},
        "secret_scanning_push_protection": {"status": "enabled"},
    },
}
PROTECTION = {
    "required_pull_request_reviews": {"required_approving_review_count": 0},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
}


class _Response(io.BytesIO):
    def __init__(self, status: int, body: bytes = b"") -> None:
        super().__init__(body)
        self.status = status


def _opener(answers: dict[str, tuple[int, object]]):
    def opener(request, timeout):  # type: ignore[no-untyped-def]
        path = request.full_url.split("/repos/ImranAdan/infra-fleet-public", 1)[1] or "/"
        assert request.get_header("Authorization") == "Bearer t0ken"
        status, body = answers[path]
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)
        return _Response(status, body if isinstance(body, bytes) else json.dumps(body).encode())

    return opener


def _answers(**changes: tuple[int, object]) -> dict[str, tuple[int, object]]:
    answers: dict[str, tuple[int, object]] = {
        "/automated-security-fixes": (200, {"enabled": True}),
        "/vulnerability-alerts": (204, b""),
        "/": (200, REPO),
        "/branches/main/protection": (200, PROTECTION),
    }
    answers.update(
        {f"/{k.replace('_', '-')}" if k != "root" else "/": v for k, v in changes.items()}
    )
    return answers


def _fetch(answers: dict[str, tuple[int, object]]) -> dict[str, object]:
    return fetch_settings("ImranAdan/infra-fleet-public", "t0ken", "T", opener=_opener(answers))


def test_reads_every_setting_with_an_administration_token() -> None:
    snapshot = _fetch(_answers())

    assert {
        key: snapshot[key]
        for key in (
            "dependabot_alerts",
            "security_updates",
            "secret_scanning",
            "push_protection",
            "default_branch_protected",
        )
    } == dict.fromkeys(
        (
            "dependabot_alerts",
            "security_updates",
            "secret_scanning",
            "push_protection",
            "default_branch_protected",
        ),
        True,
    )
    assert snapshot["reason"] == ""


def test_404s_after_a_permitted_call_mean_off_and_unprotected() -> None:
    answers = _answers()
    answers["/vulnerability-alerts"] = (404, b"")
    answers["/branches/main/protection"] = (404, b"")
    answers["/automated-security-fixes"] = (200, {"enabled": False})
    snapshot = _fetch(answers)

    assert snapshot["dependabot_alerts"] is False
    assert snapshot["security_updates"] is False
    assert snapshot["default_branch_protected"] is False


def test_force_push_or_no_pull_requests_is_unprotected() -> None:
    for protection in (
        {**PROTECTION, "allow_force_pushes": {"enabled": True}},
        {**PROTECTION, "allow_deletions": {"enabled": True}},
        {key: value for key, value in PROTECTION.items() if key != "required_pull_request_reviews"},
    ):
        answers = _answers()
        answers["/branches/main/protection"] = (200, protection)
        assert _fetch(answers)["default_branch_protected"] is False


def test_disabled_secret_scanning_is_off_and_missing_is_unknown() -> None:
    answers = _answers()
    answers["/"] = (
        200,
        {
            "default_branch": "main",
            "security_and_analysis": {"secret_scanning": {"status": "disabled"}},
        },
    )
    snapshot = _fetch(answers)

    assert snapshot["secret_scanning"] is False
    assert snapshot["push_protection"] is None
    assert "security_and_analysis unavailable" in str(snapshot["reason"])


def test_without_permission_every_value_stays_unknown() -> None:
    answers = _answers()
    answers["/automated-security-fixes"] = (403, b"")
    snapshot = _fetch(answers)

    assert all(
        snapshot[key] is None
        for key in (
            "dependabot_alerts",
            "security_updates",
            "secret_scanning",
            "push_protection",
            "default_branch_protected",
        )
    )
    assert snapshot["reason"] == "automated-security-fixes returned HTTP 403"


def test_no_token_makes_no_request() -> None:
    snapshot = fetch_settings(
        "ImranAdan/infra-fleet-public", None, "T", opener=lambda *a, **k: 1 / 0
    )
    assert snapshot["reason"] == "no settings token was provided"
