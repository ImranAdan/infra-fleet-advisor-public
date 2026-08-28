import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.report import CollectorCoverage
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_IAM_WILDCARD,
    TF_IAM_COLLECTOR_ID,
    TF_IAM_COLLECTOR_VERSION,
)

_RESOURCE_HEADER = re.compile(
    r'resource\s+"(aws_iam_policy|aws_iam_role_policy)"\s+"([A-Za-z0-9_-]+)"\s*\{'
)
_POLICY_CALL = re.compile(r"(?<!\w)policy\s*=\s*jsonencode\s*\(")
_WILDCARD_ACTION = re.compile(r"^([a-zA-Z0-9_-]+:)?\*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(#|//).*$", re.MULTILINE)
_TRAILING_COMMA = re.compile(r",(\s*[\]}])")
_BARE_KEY = re.compile(r'(?<!")\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)')
# HCL object attributes are newline-separated with no comma (`Key = value`,
# one per line); JSON requires one. Insert a comma after a value ends
# (`"`, `]`, `}`, or a digit) when the next non-blank line starts a new key
# or object, but only if a comma/brace/bracket isn't already there.
_MISSING_COMMA = re.compile(r'([\]}"0-9])(\s*\n\s*)(?=["{])')


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


class _UnbalancedError(ValueError):
    pass


def _extract_balanced(text: str, open_at: int, open_char: str, close_char: str) -> tuple[str, int]:
    """From `open_at` (pointing at `open_char`), return the substring up to
    and including the matching `close_char`, and the index just past it."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[open_at : i + 1], i + 1
    raise _UnbalancedError(f"unbalanced {open_char}{close_char}")


def _iter_resource_blocks(text: str) -> tuple[list[tuple[str, str, str]], int]:
    """Returns (resource_type, resource_name, block_body) for every
    aws_iam_policy/aws_iam_role_policy resource block in the file, plus a
    count of resource headers whose braces never balanced (a real parse
    failure — worth surfacing, not silently dropping).

    Strips `/* ... */` block comments first — otherwise a retired resource
    left inside one would still be recognized as active configuration."""
    text = _BLOCK_COMMENT.sub("", text)
    blocks = []
    unbalanced = 0
    for m in _RESOURCE_HEADER.finditer(text):
        brace_at = m.end() - 1  # the header regex consumes the opening `{`
        try:
            body, _ = _extract_balanced(text, brace_at, "{", "}")
        except _UnbalancedError:
            unbalanced += 1
            continue
        blocks.append((m.group(1), m.group(2), body))
    return blocks, unbalanced


def _extract_policy_json(block_body: str) -> tuple[dict[str, Any] | None, bool]:
    """Finds `policy = jsonencode({...})` inside a resource block body and
    parses the {...} as JSON, after normalizing HCL object-literal syntax
    (bare keys, `=` instead of `:`, trailing commas, comments) to valid JSON.

    Returns (parsed_dict_or_None, failed). `failed` is True only when a
    `policy = jsonencode(` call was found but couldn't be turned into valid
    JSON (unbalanced braces, or content this collector's literal-only
    normalizer can't handle, e.g. HCL interpolation) — a resource with no
    such attribute at all (e.g. one referencing a separate policy document)
    isn't a failure, just out of this collector's scope.
    """
    call = _POLICY_CALL.search(block_body)
    if call is None:
        return None, False
    paren_at = call.end() - 1
    try:
        _, after_paren = _extract_balanced(block_body, paren_at, "(", ")")
    except _UnbalancedError:
        return None, True
    call_args = block_body[call.end() : after_paren - 1]
    brace_at = call_args.find("{")
    if brace_at == -1:
        return None, True
    try:
        json_ish, _ = _extract_balanced(call_args, brace_at, "{", "}")
    except _UnbalancedError:
        return None, True

    normalized = _LINE_COMMENT.sub("", json_ish)
    normalized = _BARE_KEY.sub(r'"\1":', normalized)
    normalized = _MISSING_COMMA.sub(r"\1,\2", normalized)
    normalized = _TRAILING_COMMA.sub(r"\1", normalized)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        return None, True
    return (parsed, False) if isinstance(parsed, dict) else (None, True)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _statement_is_wildcard_grant(statement: dict[str, Any]) -> list[str]:
    """Returns the offending wildcard actions if this Allow statement grants
    a wildcard action on Resource: "*" (or a list containing "*")."""
    if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
        return []
    resources = _as_list(statement.get("Resource"))
    if "*" not in resources:
        return []
    actions = _as_list(statement.get("Action"))
    return [a for a in actions if isinstance(a, str) and _WILDCARD_ACTION.match(a)]


def _build_resource_evidence(
    rel_path: str, resource_type: str, resource_name: str, block_body: str
) -> tuple[Evidence | None, bool]:
    policy, failed = _extract_policy_json(block_body)
    if policy is None:
        return None, failed
    statements = policy.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]  # AWS allows a single Statement object, not just a list
    if not isinstance(statements, list):
        return None, False

    offending: list[str] = []
    matching_statement_count = 0
    for statement in statements:
        wildcards = _statement_is_wildcard_grant(statement)
        if wildcards:
            matching_statement_count += 1
            offending.extend(wildcards)
    if not offending:
        return None, False

    locator = f"resource.{resource_type}.{resource_name}.policy"
    evidence = build_evidence(
        collector_id=TF_IAM_COLLECTOR_ID,
        collector_version=TF_IAM_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        source_path=rel_path,
        locator=locator,
        excerpt=f'wildcard actions on Resource="*": {", ".join(offending[:10])}',
        fact={
            "wildcard_actions": ", ".join(offending[:10]),
            "wildcard_statement_count": matching_statement_count,
        },
        # A Terraform resource address survives a file move, so source_path
        # would make this identity positional without adding uniqueness.
        identity_parts=(locator,),
    )
    return evidence, False


def _is_excluded(rel_path: str, excluded_paths: frozenset[str]) -> bool:
    return any(
        rel_path == excluded or rel_path.startswith(f"{excluded}/") for excluded in excluded_paths
    )


def collect(
    checkout_root: Path,
    limits: ExecutionLimits,
    excluded_paths: frozenset[str] = frozenset(),
    tracked_paths: frozenset[str] | None = None,
) -> CollectorResult:
    checkout_real = checkout_root.resolve()
    infra_dir = checkout_root / "infrastructure"
    if not infra_dir.is_dir():
        # No Terraform in this repo at all — that's a legitimate, complete
        # (zero-evidence) result, not a failure. Unlike the GitHub Actions
        # workflow collector, a missing directory here must not block every
        # other collector's findings from ever being marked resolved.
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                collector_id=TF_IAM_COLLECTOR_ID,
                status="ok",
                evidence_count=0,
                error_summary=None,
            ),
        )
    if not infra_dir.resolve().is_relative_to(checkout_real):
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                collector_id=TF_IAM_COLLECTOR_ID,
                status="failed",
                evidence_count=0,
                error_summary="infrastructure directory escapes the verified checkout",
            ),
        )

    all_files = sorted(infra_dir.rglob("*.tf"))
    files = all_files[: limits.max_workflow_files]
    truncated_count = len(all_files) - len(files)

    evidence: list[Evidence] = []
    failures = 0
    excluded_count = 0
    untracked_count = 0
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
            continue
        if tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
            continue
        try:
            if path.is_symlink():
                # A tracked symlink can point at an ignored/untracked file
                # still physically inside the checkout — containment alone
                # doesn't prove the *target* was part of the verified
                # commit, so symlinks are never followed here at all.
                failures += 1
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(checkout_real):
                failures += 1
                continue
            if path.stat().st_size > limits.max_file_bytes:
                failures += 1
                continue
            text = path.read_text(encoding="utf-8")
            blocks, unbalanced = _iter_resource_blocks(text)
            failures += unbalanced
            for resource_type, resource_name, block_body in blocks:
                item, failed = _build_resource_evidence(
                    rel_path, resource_type, resource_name, block_body
                )
                if failed:
                    failures += 1
                if item is not None:
                    evidence.append(item)
        except (OSError, UnsafePathError):
            failures += 1
            continue

    if not all_files:
        status = "failed"
    elif failures or truncated_count or untracked_count:
        status = "partial"
    else:
        status = "ok"

    summary_parts = []
    if failures:
        summary_parts.append(f"{failures} unreadable/unparseable Terraform resource(s) or file(s)")
    if truncated_count:
        summary_parts.append(f"{truncated_count} Terraform file(s) omitted past max_workflow_files")
    if excluded_count:
        summary_parts.append(f"{excluded_count} Terraform file(s) excluded by policy")
    if untracked_count:
        summary_parts.append(f"{untracked_count} Terraform file(s) not part of the verified commit")

    return CollectorResult(
        evidence=tuple(evidence),
        coverage=CollectorCoverage(
            collector_id=TF_IAM_COLLECTOR_ID,
            status=status,
            evidence_count=len(evidence),
            error_summary="; ".join(summary_parts) if summary_parts else None,
        ),
    )
