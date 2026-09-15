import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence, build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.core.paths import validate_repo_relative_path
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
_POLICY_ATTRIBUTE = re.compile(r"(?<![\w.])policy\s*=")
_WILDCARD_ACTION = re.compile(r"^([a-zA-Z0-9_-]+:)?\*$")
_NON_CODE = re.compile(
    r'"(?:\\.|[^"\\])*"|/\*.*?(?:\*/|\Z)|#[^\n]*|//[^\n]*'
    r"|<<-?(?P<marker>[A-Za-z_][A-Za-z0-9_]*)[ \t]*\r?\n"
    r".*?^[ \t]*(?P=marker)[ \t]*\r?$",
    re.DOTALL | re.MULTILINE,
)
_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+'
    r"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
    r"|[A-Za-z_][A-Za-z0-9_]*|[{}\[\],:=]"
)
_TRAVERSAL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_INTERPOLATION = re.compile(r"(?<!\$)\$\{[^{}]+\}")
_MAX_LITERAL_DEPTH = 64


@dataclass(frozen=True, slots=True)
class CollectorResult:
    evidence: tuple[Evidence, ...]
    coverage: CollectorCoverage


@dataclass(frozen=True, slots=True)
class _Traversal:
    value: str


@dataclass(frozen=True, slots=True)
class _InterpolatedString:
    static_text: str


class _UnbalancedError(ValueError):
    pass


def _mask_non_code(text: str, *, strings: bool = True) -> str:
    """Keep offsets and newlines while hiding comments and optionally strings."""
    return _NON_CODE.sub(
        lambda match: (
            match.group()
            if not strings and match.group().startswith('"')
            else re.sub(r"[^\n]", " ", match.group())
        ),
        text,
    )


def _extract_balanced(text: str, open_at: int, open_char: str, close_char: str) -> tuple[str, int]:
    """From `open_at` (pointing at `open_char`), return the substring up to
    and including the matching `close_char`, and the index just past it."""
    depth = 0
    code = _mask_non_code(text)
    if "<<" in code:
        raise _UnbalancedError("unterminated Terraform heredoc")
    for i in range(open_at, len(code)):
        if code[i] == open_char:
            depth += 1
            if depth > _MAX_LITERAL_DEPTH:
                raise _UnbalancedError("Terraform literal nesting limit exceeded")
        elif code[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[open_at : i + 1], i + 1
    raise _UnbalancedError(f"unbalanced {open_char}{close_char}")


def _iter_resource_blocks(text: str) -> tuple[list[tuple[str, str, str]], int]:
    """Returns (resource_type, resource_name, block_body) for every
    aws_iam_policy/aws_iam_role_policy resource block in the file, plus a
    count of resource headers whose braces never balanced (a real parse
    failure — worth surfacing, not silently dropping).

    Comments and quoted text cannot introduce resource declarations."""
    text = _mask_non_code(text, strings=False)
    code = _mask_non_code(text)
    blocks = []
    unbalanced = 0
    for m in _RESOURCE_HEADER.finditer(text):
        if code[m.start() : m.start() + len("resource")] != "resource":
            continue
        brace_at = m.end() - 1  # the header regex consumes the opening `{`
        try:
            body, _ = _extract_balanced(text, brace_at, "{", "}")
        except _UnbalancedError:
            unbalanced += 1
            continue
        blocks.append((m.group(1), m.group(2), body))
    return blocks, unbalanced


class _LiteralParser:
    """Parse bounded JSON/HCL literals without evaluating Terraform expressions."""

    def __init__(self, text: str) -> None:
        self.tokens: list[tuple[str, bool]] = []
        previous_end = 0
        for match in _TOKEN.finditer(text):
            gap = text[previous_end : match.start()]
            if gap.strip():
                raise ValueError("unsupported Terraform expression")
            self.tokens.append((match.group(), "\n" in gap))
            previous_end = match.end()
        if text[previous_end:].strip():
            raise ValueError("unsupported Terraform expression")
        self.index = 0

    def _peek(self) -> str:
        return self.tokens[self.index][0] if self.index < len(self.tokens) else ""

    def _take(self) -> str:
        token = self._peek()
        if not token:
            raise ValueError("incomplete Terraform literal")
        self.index += 1
        return token

    def value(self, depth: int = 0) -> Any:
        if depth >= _MAX_LITERAL_DEPTH:
            raise ValueError("Terraform literal nesting limit exceeded")
        literal = self._take()
        if literal == "{":
            result: dict[str, Any] = {}
            while self._peek() != "}":
                key = self._take()
                separator = self._take()
                quoted = key.startswith('"')
                if not quoted and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    raise ValueError("invalid Terraform object key")
                if separator not in {"=", ":"} or (separator == ":" and not quoted):
                    raise ValueError("invalid Terraform object separator")
                key = json.loads(key) if quoted else key
                if key in result:
                    raise ValueError("duplicate Terraform object key")
                result[key] = self.value(depth + 1)
                if self._peek() == ",":
                    self._take()
                elif self._peek() != "}" and (
                    separator == ":"
                    or self.index >= len(self.tokens)
                    or not self.tokens[self.index][1]
                ):
                    raise ValueError("missing Terraform object separator")
            self._take()
            return result
        if literal == "[":
            values: list[Any] = []
            while self._peek() != "]":
                values.append(self.value(depth + 1))
                if self._peek() == ",":
                    self._take()
                elif self._peek() != "]":
                    raise ValueError("missing Terraform list separator")
            self._take()
            return values
        if literal.startswith('"'):
            decoded = json.loads(literal)
            if re.search(r"(?<!%)%\{", decoded):
                raise ValueError("Terraform template directives are unsupported")
            static_text = _INTERPOLATION.sub("", decoded)
            if re.search(r"(?<!\$)\$\{", static_text):
                raise ValueError("malformed Terraform string interpolation")
            if static_text != decoded:
                return _InterpolatedString(static_text=static_text)
            return decoded.replace("$${", "${").replace("%%{", "%{")
        if literal in {"true", "false", "null"} or re.fullmatch(r"-?[0-9].*", literal):
            return json.loads(literal)
        if _TRAVERSAL.fullmatch(literal):
            return _Traversal(literal)
        raise ValueError("unsupported Terraform expression")


def _extract_policy_json(block_body: str) -> tuple[dict[str, Any] | None, bool]:
    """Finds `policy = jsonencode({...})` inside a resource block body and
    parses bounded JSON/HCL literals, including quoted keys and comments.

    Returns (parsed_dict_or_None, failed). Missing attributes, non-literal
    expressions, and malformed literals are incomplete coverage. Referenced
    policy documents are never fetched or executed.
    """
    code = _mask_non_code(block_body)
    assignments = [
        match
        for match in _POLICY_ATTRIBUTE.finditer(code)
        if code[: match.start()].count("{") - code[: match.start()].count("}") == 1
    ]
    if len(assignments) != 1:
        return None, True
    call = _POLICY_CALL.match(code, assignments[0].start())
    if call is None:
        return None, True
    paren_at = call.end() - 1
    try:
        _, after_paren = _extract_balanced(block_body, paren_at, "(", ")")
    except _UnbalancedError:
        return None, True
    suffix = _mask_non_code(block_body[after_paren:], strings=False)
    if not re.match(r"^[ \t\r]*(?:\n\s*)*(?:\}|[A-Za-z_][A-Za-z0-9_]*\s*=)", suffix):
        return None, True
    call_args = block_body[call.end() : after_paren - 1]
    try:
        parser = _LiteralParser(_mask_non_code(call_args, strings=False))
        parsed = parser.value()
        if parser.index != len(parser.tokens):
            return None, True
    except ValueError:
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
    if not isinstance(statements, list) or not statements:
        return None, True

    offending: list[str] = []
    matching_statement_count = 0
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("Effect") not in ("Allow", "Deny"):
            return None, True
        actions = _as_list(statement.get("Action"))
        if not actions or any(not isinstance(value, str) or not value for value in actions):
            return None, True
        resources = _as_list(statement.get("Resource"))
        if not resources:
            return None, True
        for value in resources:
            if isinstance(value, str) and value:
                continue
            # An interpolated ARN with a fixed non-wildcard character cannot
            # evaluate to the exact Resource "*" this collector detects. A
            # traversal or interpolation-only value remains unknown and fails
            # closed rather than being treated as scoped.
            if isinstance(value, _InterpolatedString) and value.static_text.strip("*"):
                continue
            return None, True
        wildcards = _statement_is_wildcard_grant(statement)
        if wildcards:
            matching_statement_count += 1
            offending.extend(wildcards)
    if not offending:
        return None, False

    locator = f"resource.{resource_type}.{resource_name}.policy"
    safe_path = validate_repo_relative_path(rel_path)
    root_module = PurePosixPath(safe_path).parent.as_posix()
    evidence = build_evidence(
        collector_id=TF_IAM_COLLECTOR_ID,
        collector_version=TF_IAM_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        source_path=safe_path,
        locator=locator,
        excerpt=f'wildcard actions on Resource="*": {", ".join(offending[:10])}',
        fact={
            "wildcard_actions": ", ".join(offending[:10]),
            "wildcard_statement_count": matching_statement_count,
        },
        # A resource address is unique only within its root module. Keep that
        # directory namespace while excluding the .tf filename so file moves
        # within a module preserve identity without conflating separate roots.
        identity_parts=(root_module, locator),
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
    included_path_prefixes: tuple[str, ...] = (),
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

    # Downloaded modules are local tool state, not fleet desired state. Keep a
    # deliberately tracked cache path visible, but ignore ordinary .terraform
    # files before applying the bounded source-file budget.
    all_files = sorted(
        path
        for path in infra_dir.rglob("*.tf")
        if (
            not included_path_prefixes
            or any(
                path.relative_to(checkout_root).as_posix() == prefix
                or path.relative_to(checkout_root).as_posix().startswith(f"{prefix}/")
                for prefix in included_path_prefixes
            )
        )
        and (
            ".terraform" not in path.relative_to(infra_dir).parts
            or (
                tracked_paths is not None
                and path.relative_to(checkout_root).as_posix() in tracked_paths
            )
        )
    )
    eligible_files: list[Path] = []
    excluded_count = 0
    untracked_count = 0
    for path in all_files:
        rel_path = path.relative_to(checkout_root).as_posix()
        if _is_excluded(rel_path, excluded_paths):
            excluded_count += 1
        elif tracked_paths is not None and rel_path not in tracked_paths:
            untracked_count += 1
        else:
            eligible_files.append(path)
    files = eligible_files[: limits.max_workflow_files]
    truncated_count = len(eligible_files) - len(files)

    evidence: list[Evidence] = []
    failures = 0
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
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
