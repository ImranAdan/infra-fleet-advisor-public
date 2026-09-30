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
# Every block that could declare or attach IAM: `module` has one label.
_BLOCK_HEADER = re.compile(
    r'(?<![\w.-])(resource|data|module)\s+"([A-Za-z0-9_-]+)"(?:\s+"([A-Za-z0-9_-]+)")?\s*\{'
)
_TOP_LEVEL_NAME = re.compile(r"(?<![\w.$-])([A-Za-z_][\w-]*)\s*(=(?![=>])|\{)")
_POLICY_NAME = re.compile(r"(?:^|_)polic(?:y|ies)(?:_|$)")
_IAM_TYPE = re.compile(r"(?:^|_)iam(?:_|$)")
_POLICY_DOCUMENT_TYPES = frozenset(
    {"aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"}
)
_ATTACHMENT_TYPES = frozenset(
    {
        "aws_iam_policy_attachment",
        "aws_iam_role_policy_attachment",
        "aws_iam_user_policy_attachment",
        "aws_iam_group_policy_attachment",
    }
)
# The closed set of blocks whose policy-named attributes this collector
# accounts for. Any other IAM type, any other policy-named attribute, and any
# module leaves persistent IAM incomplete rather than silently unexamined.
_POLICY_ATTRIBUTES: dict[tuple[str, str], frozenset[str]] = {
    **{("resource", kind): frozenset({"policy"}) for kind in _POLICY_DOCUMENT_TYPES},
    **{("resource", kind): frozenset({"policy_arn"}) for kind in _ATTACHMENT_TYPES},
    # A trust policy decides who may assume the role; it grants no actions.
    ("resource", "aws_iam_role"): frozenset({"assume_role_policy"}),
    ("resource", "aws_iam_openid_connect_provider"): frozenset(),
    ("data", "aws_iam_policy_document"): frozenset(),
    # Image expiry rules, not an IAM document.
    ("resource", "aws_ecr_lifecycle_policy"): frozenset({"policy"}),
}
_DOCUMENT_STATEMENT_KEYS = {
    "sid": "",
    "effect": "Effect",
    "actions": "Action",
    "resources": "Resource",
}
_DOCUMENT_SUB_BLOCKS = frozenset({"condition", "principals", "not_principals"})
_POLICY_REFERENCE = re.compile(
    r"(?<!\w)policy\s*=\s*data\.aws_iam_policy_document\.([A-Za-z0-9_-]+)\.json"
)
_ATTACHMENT_REFERENCE = re.compile(
    r"(?<![\w.])policy_arn\s*=\s*aws_iam_policy\.([A-Za-z0-9_-]+)\.arn"
)
_EXPRESSION_END = re.compile(r"^[ \t\r]*(?:\n\s*)*(?:\}|[A-Za-z_][A-Za-z0-9_]*\s*=)")
_POLICY_CALL = re.compile(r"(?<!\w)policy\s*=\s*jsonencode\s*\(")
_POLICY_ATTRIBUTE = re.compile(r"(?<![\w.])policy\s*=")
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


def _iter_resource_blocks(
    text: str, header: re.Pattern[str] = _RESOURCE_HEADER
) -> tuple[list[tuple[str, ...]], int]:
    """Returns (*header groups, block_body) for every block whose header
    matches — by default (resource_type, resource_name) of IAM policy
    resources — plus a count of headers whose braces never balanced (a real
    parse failure — worth surfacing, not silently dropping).

    Comments and quoted text cannot introduce block declarations."""
    text = _mask_non_code(text, strings=False)
    code = _mask_non_code(text)
    blocks = []
    unbalanced = 0
    for m in header.finditer(text):
        if code[m.start()] != text[m.start()]:
            continue
        brace_at = m.end() - 1  # the header regex consumes the opening `{`
        try:
            body, _ = _extract_balanced(text, brace_at, "{", "}")
        except _UnbalancedError:
            unbalanced += 1
            continue
        blocks.append((*(group or "" for group in m.groups()), body))
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


def _extract_policy_json(
    block_body: str, documents: frozenset[str] = frozenset()
) -> tuple[dict[str, Any] | None, bool]:
    """Finds `policy = jsonencode({...})` inside a resource block body and
    parses bounded JSON/HCL literals, including quoted keys and comments.

    Returns (parsed_dict_or_None, failed). Missing attributes, non-literal
    expressions, and malformed literals are incomplete coverage. A reference
    to `data.aws_iam_policy_document.<name>.json` is complete only when that
    document is in `documents`, the literal ones parsed in the same root
    module, which are evaluated on their own. Nothing is fetched or executed.
    """
    code = _mask_non_code(block_body)
    assignments = [
        match
        for match in _POLICY_ATTRIBUTE.finditer(code)
        if code[: match.start()].count("{") - code[: match.start()].count("}") == 1
    ]
    if len(assignments) != 1:
        return None, True
    reference = _POLICY_REFERENCE.match(code, assignments[0].start())
    if reference is not None:
        complete = bool(_EXPRESSION_END.match(code[reference.end() :]))
        return None, not (complete and reference.group(1) in documents)
    call = _POLICY_CALL.match(code, assignments[0].start())
    if call is None:
        return None, True
    paren_at = call.end() - 1
    try:
        _, after_paren = _extract_balanced(block_body, paren_at, "(", ")")
    except _UnbalancedError:
        return None, True
    suffix = _mask_non_code(block_body[after_paren:], strings=False)
    if not _EXPRESSION_END.match(suffix):
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


def _is_service_wide(action: str) -> bool:
    """`*`, `eks:*` or a wildcard service; a prefix like `ec2:Describe*` is not."""
    service, separator, name = action.partition(":")
    if not separator:
        return "*" in action
    return bool(re.search(r"[*?]", service)) or re.fullmatch(r"[*?]*\*[*?]*", name) is not None


def _statement_is_wildcard_grant(statement: dict[str, Any]) -> list[str]:
    """Returns the service-wide wildcard actions this Allow statement grants,
    whatever its Resource: a scoped ARN still grants every action of the service."""
    if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
        return []
    actions = _as_list(statement.get("Action"))
    return [a for a in actions if isinstance(a, str) and _is_service_wide(a)]


def _wildcard_grants(policy: dict[str, Any]) -> tuple[list[str], int] | None:
    """(offending actions, statement count), or None when a decision field is unknown."""
    statements = policy.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]  # AWS allows a single Statement object, not just a list
    if not isinstance(statements, list) or not statements:
        return None

    offending: list[str] = []
    matching_statement_count = 0
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("Effect") not in ("Allow", "Deny"):
            return None
        actions = _as_list(statement.get("Action"))
        if not actions or any(not isinstance(value, str) or not value for value in actions):
            return None
        resources = _as_list(statement.get("Resource"))
        if not resources:
            return None
        for value in resources:
            if isinstance(value, str) and value:
                continue
            # An interpolated ARN with a fixed non-wildcard character cannot
            # evaluate to the exact Resource "*" this collector detects. A
            # traversal or interpolation-only value remains unknown and fails
            # closed rather than being treated as scoped.
            if isinstance(value, _InterpolatedString) and value.static_text.strip("*"):
                continue
            return None
        wildcards = _statement_is_wildcard_grant(statement)
        if wildcards:
            matching_statement_count += 1
            offending.extend(wildcards)
    return offending, matching_statement_count


def _build_resource_evidence(
    rel_path: str,
    resource_type: str,
    resource_name: str,
    block_body: str,
    documents: frozenset[str] = frozenset(),
) -> tuple[Evidence | None, bool]:
    policy, failed = _extract_policy_json(block_body, documents)
    if policy is None:
        return None, failed
    grants = _wildcard_grants(policy)
    if grants is None:
        return None, True
    locator = f"resource.{resource_type}.{resource_name}.policy"
    return _wildcard_evidence(rel_path, locator, *grants), False


def _wildcard_evidence(
    rel_path: str, locator: str, offending: list[str], matching_statement_count: int
) -> Evidence | None:
    if not offending:
        return None
    safe_path = validate_repo_relative_path(rel_path)
    root_module = PurePosixPath(safe_path).parent.as_posix()
    evidence = build_evidence(
        collector_id=TF_IAM_COLLECTOR_ID,
        collector_version=TF_IAM_COLLECTOR_VERSION,
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        source_path=safe_path,
        locator=locator,
        excerpt=f"service-wide wildcard actions: {', '.join(offending[:10])}",
        fact={
            "wildcard_actions": ", ".join(offending[:10]),
            "wildcard_statement_count": matching_statement_count,
        },
        # A resource address is unique only within its root module. Keep that
        # directory namespace while excluding the .tf filename so file moves
        # within a module preserve identity without conflating separate roots.
        identity_parts=(root_module, locator),
    )
    return evidence


def _top_level_names(block_body: str) -> list[re.Match[str]]:
    """Attribute and nested-block names directly inside `block_body` (`{...}`)."""
    code = _mask_non_code(block_body)
    names = []
    depth, last = 0, 0
    for match in _TOP_LEVEL_NAME.finditer(code):
        depth += code.count("{", last, match.start()) - code.count("}", last, match.start())
        last = match.start()
        if depth == 1:
            names.append(match)
    return names


def _hides_iam(kind: str, block_type: str, block_body: str) -> bool:
    """True when a block may grant IAM this collector does not account for."""
    allowed = _POLICY_ATTRIBUTES.get((kind, block_type))
    if kind == "module" or (allowed is None and _IAM_TYPE.search(block_type)):
        return True
    iam = allowed is not None and bool(_IAM_TYPE.search(block_type))
    labels = _mask_non_code(block_body, strings=False)
    for match in _top_level_names(block_body):
        name = match.group(1)
        if name == "dynamic":
            if iam:
                return True
            label = re.match(r'dynamic\s+"([^"]*)"', labels[match.start() :])
            name = label.group(1) if label else name
        if _POLICY_NAME.search(name) and name not in (allowed or frozenset()):
            return True
    return False


def _policy_document(block_body: str) -> dict[str, Any] | None:
    """A literal `aws_iam_policy_document` in the JSON statement shape, or None."""
    names = _top_level_names(block_body)
    if any(match.group(1) not in {"statement", "version", "policy_id"} for match in names):
        return None
    statements = []
    for match in names:
        if match.group(1) != "statement":
            continue
        if match.group(2) != "{":
            return None
        try:
            body, _ = _extract_balanced(block_body, match.end() - 1, "{", "}")
        except _UnbalancedError:
            return None
        for sub in reversed(_top_level_names(body)):
            if sub.group(2) != "{":
                continue
            if sub.group(1) not in _DOCUMENT_SUB_BLOCKS:
                return None
            try:
                _, end = _extract_balanced(body, sub.end() - 1, "{", "}")
            except _UnbalancedError:
                return None
            body = body[: sub.start()] + re.sub(r"[^\n]", " ", body[sub.start() : end]) + body[end:]
        try:
            parser = _LiteralParser(_mask_non_code(body, strings=False))
            parsed = parser.value()
        except ValueError:
            return None
        if parser.index != len(parser.tokens) or not isinstance(parsed, dict):
            return None
        if not set(parsed) <= set(_DOCUMENT_STATEMENT_KEYS):
            return None  # not_actions, not_resources and unknown keys stay unknown
        statement = {"Effect": parsed.get("effect", "Allow")}
        statement |= {_DOCUMENT_STATEMENT_KEYS[k]: v for k, v in parsed.items() if k != "sid"}
        statements.append(statement)
    return {"Statement": statements}


def _attachment_target(block_body: str) -> str | None:
    """The same-module `aws_iam_policy` an attachment names, or None if unknown."""
    code = _mask_non_code(block_body)
    arns = [m for m in _top_level_names(block_body) if m.group(1) == "policy_arn"]
    if len(arns) != 1:
        return None
    target = _ATTACHMENT_REFERENCE.match(code, arns[0].start())
    if target is None or not _EXPRESSION_END.match(code[target.end() :]):
        return None
    return target.group(1)


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
        # other collector's findings from ever being marked resolved. A
        # declared scope that is missing, though, proves nothing about it.
        return CollectorResult(
            evidence=(),
            coverage=CollectorCoverage(
                collector_id=TF_IAM_COLLECTOR_ID,
                status="failed" if included_path_prefixes else "ok",
                evidence_count=0,
                error_summary="declared Terraform scope is missing"
                if included_path_prefixes
                else None,
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
        for path in (*infra_dir.rglob("*.tf"), *infra_dir.rglob("*.tf.json"))
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
    blocks: list[tuple[str, str, str, str, str, str]] = []
    for path in files:
        rel_path = str(path.relative_to(checkout_root))
        try:
            if path.name.endswith(".tf.json") or path.stem.endswith("override"):
                # JSON syntax and override files can declare or replace IAM
                # this HCL parser never reads.
                failures += 1
                continue
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
            file_blocks, unbalanced = _iter_resource_blocks(text, _BLOCK_HEADER)
            failures += unbalanced
            module = PurePosixPath(rel_path).parent.as_posix()
            blocks.extend((rel_path, module, k, t, n, b) for k, t, n, b in file_blocks)
        except (OSError, UnsafePathError, UnicodeDecodeError):
            failures += 1
            continue

    # Resolve references within each root module only after every file is read.
    addresses = [(module, kind, kind_type, name) for _, module, kind, kind_type, name, _ in blocks]
    failures += len(addresses) - len(set(addresses))
    policies = {
        (module, name)
        for module, kind, kind_type, name in addresses
        if (kind, kind_type) == ("resource", "aws_iam_policy")
    }
    documents: dict[str, set[str]] = {}
    for rel_path, module, kind, block_type, name, body in blocks:
        if _hides_iam(kind, block_type, body):
            failures += 1
        elif (kind, block_type) == ("data", "aws_iam_policy_document"):
            document = _policy_document(body)
            grants = None if document is None else _wildcard_grants(document)
            if grants is None:
                failures += 1
                continue
            documents.setdefault(module, set()).add(name)
            item = _wildcard_evidence(rel_path, f"data.{block_type}.{name}", *grants)
            evidence.extend([item] if item else [])
        elif kind == "resource" and block_type in _ATTACHMENT_TYPES:
            failures += (module, _attachment_target(body)) not in policies
    for rel_path, module, kind, block_type, name, body in blocks:
        if (
            kind == "resource"
            and block_type in _POLICY_DOCUMENT_TYPES
            and not _hides_iam(kind, block_type, body)
        ):
            item, failed = _build_resource_evidence(
                rel_path, block_type, name, body, frozenset(documents.get(module, ()))
            )
            failures += failed
            evidence.extend([item] if item else [])

    if not all_files:
        status = "failed"
    elif failures or truncated_count or untracked_count or excluded_count:
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
