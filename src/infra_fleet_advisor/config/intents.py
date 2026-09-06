import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from infra_fleet_advisor.core.contracts import PRIORITIES
from infra_fleet_advisor.core.errors import PolicyError
from infra_fleet_advisor.core.validation import contains_secret

MAX_INTENT_FILES = 20
MAX_INTENT_FILE_BYTES = 64 * 1024
MAX_INTENT_PROPOSITIONS = 100
MAX_INTENT_STATEMENT_LENGTH = 4000

_DOCUMENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PROPOSITION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECK_KEY = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_PROPOSITION_HEADING = re.compile(
    r"^## (?P<identifier>[A-Za-z0-9][A-Za-z0-9._-]{0,63}) · (?P<title>[^\r\n]{1,120})$"
)
_EVALUATION_FIELD = re.compile(r"^- (?P<key>Check|Priority): `(?P<value>[^`\r\n]+)`$")
_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")


@dataclass(frozen=True, slots=True)
class IntentProposition:
    document_id: str
    document_version: str
    proposition_id: str
    category: str
    priority: str | None
    statement: str
    check_key: str | None


@dataclass(frozen=True, slots=True)
class IntentCatalog:
    digest: str
    propositions: tuple[IntentProposition, ...]


def _bounded_one_line(value: str, field_name: str, maximum: int) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise PolicyError(f"{field_name} must be a bounded, non-empty single-line string")
    return value


def _bounded_markdown(value: str) -> str:
    statement = value.strip()
    if (
        not statement
        or len(statement) > MAX_INTENT_STATEMENT_LENGTH
        or any(ord(character) < 32 and character not in ("\n", "\t") for character in statement)
    ):
        raise PolicyError("intent text must be bounded, non-empty Markdown")
    if contains_secret(statement):
        raise PolicyError("intent text contains a secret-like value")
    return statement


def _structural_headings(lines: list[str]) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        fence = _FENCE.match(line)
        if fence is not None:
            marker = fence.group("marker")
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is None and line.startswith("#"):
            headings.append((index, line))
    if fence_character is not None:
        raise PolicyError("intent document contains an unclosed Markdown fence")
    return headings


def _document_metadata(lines: list[str]) -> tuple[str, str, str]:
    if not lines or not re.fullmatch(r"# [^\r\n]{1,120}", lines[0]):
        raise PolicyError("intent document must start with one level-one title")
    expected = (
        ("- Format: `", "1"),
        ("- Intent ID: `", None),
        ("- Version: `", None),
        ("- Category: `", None),
    )
    if len(lines) < 6 or lines[1] != "":
        raise PolicyError("intent document metadata block is missing")
    values: list[str] = []
    for line, (prefix, fixed_value) in zip(lines[2:6], expected, strict=True):
        if not line.startswith(prefix) or not line.endswith("`"):
            raise PolicyError("intent document metadata block is invalid")
        value = line[len(prefix) : -1]
        if fixed_value is not None and value != fixed_value:
            raise PolicyError("intent Markdown format must be 1")
        values.append(value)
    document_id = _bounded_one_line(values[1], "intent id", 64)
    if not _DOCUMENT_ID.fullmatch(document_id):
        raise PolicyError("intent id must be a safe identifier")
    document_version = _bounded_one_line(values[2], "intent version", 64)
    category = _bounded_one_line(values[3], "intent category", 64)
    return document_id, document_version, category


def _evaluation_metadata(lines: list[str]) -> tuple[str | None, str | None]:
    fields: dict[str, str] = {}
    for line in lines:
        if not line:
            continue
        match = _EVALUATION_FIELD.fullmatch(line)
        if match is None or match.group("key") in fields:
            raise PolicyError("intent evaluation metadata is invalid")
        fields[match.group("key")] = match.group("value")
    if not fields:
        raise PolicyError("intent Evaluation section must not be empty")
    check_key = fields.get("Check")
    if check_key is not None:
        check_key = _bounded_one_line(check_key, "intent check", 64)
        if not _CHECK_KEY.fullmatch(check_key):
            raise PolicyError("intent check must be a safe identifier")
    priority = fields.get("Priority")
    if priority is not None:
        priority = _bounded_one_line(priority, "intent priority", 16)
        if priority not in PRIORITIES:
            raise PolicyError("intent priority is not recognized")
    return check_key, priority


def _load_document(path: Path, taxonomy: frozenset[str]) -> tuple[IntentProposition, ...]:
    if path.is_symlink():
        raise PolicyError("intent documents must not be symbolic links")
    try:
        if path.stat().st_size > MAX_INTENT_FILE_BYTES:
            raise PolicyError(f"intent document exceeds {MAX_INTENT_FILE_BYTES} bytes")
        text = path.read_text(encoding="utf-8")
    except PolicyError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PolicyError(f"cannot read intent document: {type(exc).__name__}") from exc
    if "\r" in text:
        raise PolicyError("intent documents must use normalized line endings")
    lines = text.splitlines()
    document_id, document_version, category = _document_metadata(lines)
    if category not in taxonomy:
        raise PolicyError("intent category is not in the closed taxonomy")

    headings = _structural_headings(lines)
    if not headings or headings[0] != (0, lines[0]):
        raise PolicyError("intent document title is invalid")
    proposition_starts: list[tuple[int, re.Match[str]]] = []
    for index, heading in headings[1:]:
        if heading.startswith("## ") and not heading.startswith("### "):
            match = _PROPOSITION_HEADING.fullmatch(heading)
            if match is None:
                raise PolicyError("intent proposition heading is invalid")
            proposition_starts.append((index, match))
        elif heading.startswith("# "):
            raise PolicyError("intent document may contain only one level-one title")
    if not proposition_starts:
        raise PolicyError("intent document contains no propositions")

    propositions: list[IntentProposition] = []
    seen_ids: set[str] = set()
    for position, (start, heading_match) in enumerate(proposition_starts):
        end = (
            proposition_starts[position + 1][0]
            if position + 1 < len(proposition_starts)
            else len(lines)
        )
        proposition_id = heading_match.group("identifier")
        title = _bounded_one_line(heading_match.group("title"), "intent title", 120)
        if not _PROPOSITION_ID.fullmatch(proposition_id) or proposition_id in seen_ids:
            raise PolicyError("intent proposition ids must be safe and unique per document")
        if title.startswith("#"):
            raise PolicyError("intent title is invalid")
        seen_ids.add(proposition_id)

        subheadings = [
            (index, heading)
            for index, heading in headings
            if start < index < end and heading.startswith("### ")
        ]
        if not subheadings or subheadings[0][1] != "### Intent":
            raise PolicyError("intent proposition must start with an Intent section")
        if any(heading not in ("### Intent", "### Evaluation") for _, heading in subheadings):
            raise PolicyError("intent proposition contains an unsupported section")
        if len({heading for _, heading in subheadings}) != len(subheadings):
            raise PolicyError("intent proposition sections must be unique")
        if len(subheadings) == 2 and subheadings[1][1] != "### Evaluation":
            raise PolicyError("intent Evaluation section must follow Intent")

        intent_start = subheadings[0][0] + 1
        intent_end = subheadings[1][0] if len(subheadings) == 2 else end
        statement = _bounded_markdown("\n".join(lines[intent_start:intent_end]))
        check_key = None
        priority = None
        if len(subheadings) == 2:
            check_key, priority = _evaluation_metadata(lines[subheadings[1][0] + 1 : end])
        propositions.append(
            IntentProposition(
                document_id=document_id,
                document_version=document_version,
                proposition_id=proposition_id,
                category=category,
                priority=priority,
                statement=statement,
                check_key=check_key,
            )
        )
    return tuple(propositions)


def load_intent_catalog(directory: Path, taxonomy: frozenset[str]) -> IntentCatalog:
    """Load bounded Markdown intent without turning prose into executable code."""
    if not directory.is_dir():
        raise PolicyError("intent directory does not exist")
    paths = sorted(path for path in directory.iterdir() if path.suffix.casefold() == ".md")
    if not paths:
        raise PolicyError("intent directory contains no Markdown documents")
    if len(paths) > MAX_INTENT_FILES:
        raise PolicyError(f"intent directory exceeds {MAX_INTENT_FILES} documents")

    propositions: list[IntentProposition] = []
    document_ids: set[str] = set()
    proposition_keys: set[tuple[str, str]] = set()
    declared_checks: set[str] = set()
    for path in paths:
        document = _load_document(path, taxonomy)
        document_id = document[0].document_id
        if document_id in document_ids:
            raise PolicyError("intent document ids must be unique")
        document_ids.add(document_id)
        for proposition in document:
            key = (proposition.document_id, proposition.proposition_id)
            if key in proposition_keys:
                raise PolicyError("intent proposition identity must be unique")
            proposition_keys.add(key)
            if proposition.check_key is not None:
                if proposition.check_key in declared_checks:
                    raise PolicyError("an intent check may be declared only once")
                declared_checks.add(proposition.check_key)
            propositions.append(proposition)

    if len(propositions) > MAX_INTENT_PROPOSITIONS:
        raise PolicyError(f"intent catalog exceeds {MAX_INTENT_PROPOSITIONS} propositions")
    ordered = tuple(sorted(propositions, key=lambda item: (item.document_id, item.proposition_id)))
    canonical = json.dumps(
        [asdict(proposition) for proposition in ordered],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = "intent-md-v1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return IntentCatalog(digest=digest, propositions=ordered)
