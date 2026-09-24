from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.collectors import (
    application_config_collector as collector,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)
APP = "from flask import Flask\napp = Flask(__name__)\n%s\n"


def _fact(tmp_path: Path, body: str) -> dict[str, object]:
    path = tmp_path / "applications" / "web" / "src" / "app.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(APP % body, encoding="utf-8")
    result = collector.collect(tmp_path, LIMITS)
    assert result.coverage.status == "ok"
    [evidence] = result.evidence
    return dict(evidence.fact)


def test_samesite_lax_or_strict_with_httponly_compensates(tmp_path: Path) -> None:
    cases = {
        'app.config["SESSION_COOKIE_SAMESITE"] = "Lax"': True,
        'app.config["SESSION_COOKIE_SAMESITE"] = "Strict"': True,
        'app.config["SESSION_COOKIE_SAMESITE"] = "None"': False,
        "": False,  # Flask's default sends no SameSite attribute
        'app.config["SESSION_COOKIE_SAMESITE"] = "Lax"\n'
        'app.config["SESSION_COOKIE_HTTPONLY"] = False': False,
        'app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("X")': False,
    }
    for body, compensated in cases.items():
        assert _fact(tmp_path, body)["csrf_compensated"] is compensated, body


def test_code_is_parsed_not_executed_and_tests_are_ignored(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    tests = tmp_path / "applications" / "web" / "tests" / "test_app.py"
    tests.parent.mkdir(parents=True)
    tests.write_text('app.config["SESSION_COOKIE_SAMESITE"] = "None"\n', encoding="utf-8")

    fact = _fact(
        tmp_path,
        f'open("{marker}", "w")\napp.config["SESSION_COOKIE_SAMESITE"] = "Lax"',
    )

    assert fact["csrf_compensated"] is True
    assert not marker.exists()


def test_non_flask_applications_are_not_evidence(tmp_path: Path) -> None:
    path = tmp_path / "applications" / "cli" / "main.py"
    path.parent.mkdir(parents=True)
    path.write_text("print('hi')\n", encoding="utf-8")

    assert collector.collect(tmp_path, LIMITS).evidence == ()
