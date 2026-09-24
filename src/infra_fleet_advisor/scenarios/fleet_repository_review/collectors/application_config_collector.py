"""Security-relevant literal configuration in tracked Flask applications.

Source is parsed with `ast` and never imported or executed. Only literal
assignments of the form `app.config["KEY"] = <constant>` are read; the last
one in a module wins, matching run order within that module.
"""

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    APP_CONFIG_COLLECTOR_ID,
    APP_CONFIG_COLLECTOR_VERSION,
    EVIDENCE_KIND_SESSION_COOKIE,
)

_KEYS = ("SESSION_COOKIE_SAMESITE", "SESSION_COOKIE_HTTPONLY")


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


def _config_assignments(tree: ast.Module) -> dict[str, object]:
    found: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "config"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value in _KEYS
        ):
            value = (
                node.value.value if isinstance(node.value, ast.Constant) else ast.dump(node.value)
            )
            found[str(target.slice.value)] = value
    return found


def _uses_flask(tree: ast.Module) -> bool:
    return any(
        (isinstance(node, ast.ImportFrom) and node.module == "flask")
        or (isinstance(node, ast.Import) and any(a.name == "flask" for a in node.names))
        for node in ast.walk(tree)
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    """One record per application directory that imports Flask."""
    root = checkout_root / "applications"
    if not root.is_dir():
        return CollectorResult((), CollectorCoverage(APP_CONFIG_COLLECTOR_ID, "ok", 0))
    checkout_real = checkout_root.resolve()
    failures = 0
    apps: dict[str, dict[str, object]] = {}
    first_file: dict[str, str] = {}
    flask_apps: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        rel_path = path.relative_to(checkout_root).as_posix()
        parts = PurePosixPath(rel_path).parts
        if "tests" in parts or (tracked_paths is not None and rel_path not in tracked_paths):
            continue
        if any(rel_path == ex or rel_path.startswith(f"{ex}/") for ex in excluded_paths):
            continue
        app = "/".join(parts[:2])
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(checkout_real):
                raise ValueError("not a regular in-checkout file")
            if path.stat().st_size > limits.max_file_bytes:
                raise ValueError("file exceeds max_file_bytes")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        except (OSError, UnicodeError, ValueError, SyntaxError):
            failures += 1
            continue
        if _uses_flask(tree):
            flask_apps.add(app)
        assignments = _config_assignments(tree)
        if assignments:
            apps.setdefault(app, {}).update(assignments)
            first_file.setdefault(app, rel_path)

    evidence = []
    for app in sorted(flask_apps):
        config = apps.get(app, {})
        samesite = config.get("SESSION_COOKIE_SAMESITE")
        httponly = config.get("SESSION_COOKIE_HTTPONLY", True)  # Flask's default
        compensated = samesite in {"Lax", "Strict"} and httponly is True
        evidence.append(
            build_evidence(
                collector_id=APP_CONFIG_COLLECTOR_ID,
                collector_version=APP_CONFIG_COLLECTOR_VERSION,
                kind=EVIDENCE_KIND_SESSION_COOKIE,
                source_path=first_file.get(app, app),
                locator=f"{app} session cookie",
                excerpt=f"{app}: SameSite={samesite!s:.40}, HttpOnly={httponly!s:.40}",
                fact={
                    "samesite": str(samesite)[:40],
                    "httponly": httponly is True,
                    "csrf_compensated": compensated,
                },
                identity_parts=(app, "session cookie"),
            )
        )
    return CollectorResult(
        tuple(evidence),
        CollectorCoverage(
            APP_CONFIG_COLLECTOR_ID,
            "partial" if failures else "ok",
            len(evidence),
            f"{failures} application source file(s) could not be parsed" if failures else None,
        ),
    )
