"""Prove each registered check still sees the real fleet.

A drill applies one literal, declared violation to a throwaway worktree of the
fleet, runs the ordinary review, and expects the named proposition to diverge,
or, with `expect: declared_unverified`, to lose a proof it held on the fleet.
A drill may list variants: the first whose text the fleet still contains is
applied, so a drill can match the fleet before and after a change to it.
Drills are trusted data from this repository; the fleet is only read and its
worktree is removed afterwards.
"""

import json
import subprocess  # noqa: S404 - fixed git argv only
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from infra_fleet_advisor.core.errors import PolicyError, UnsafePathError
from infra_fleet_advisor.core.paths import validate_repo_relative_path

DrillOutcome = Literal["caught", "missed", "stale", "already_divergent"]
_EXPECTATIONS = {"divergent", "declared_unverified"}
_MAX_DRILLS = 64
_MAX_VARIANTS = 8
_MUTATION_FIELDS = {"path", "find", "replace"}


@dataclass(frozen=True, slots=True)
class Mutation:
    path: str
    find: str
    replace: str


@dataclass(frozen=True, slots=True)
class Drill:
    proposition: str
    path: str
    find: str
    replace: str
    alternatives: tuple[Mutation, ...] = ()
    expect: str = "divergent"

    def mutations(self) -> tuple[Mutation, ...]:
        return (Mutation(self.path, self.find, self.replace), *self.alternatives)


@dataclass(frozen=True, slots=True)
class DrillResult:
    drill: Drill
    outcome: DrillOutcome
    applied: Mutation | None = None


def _mutation(proposition: str, item: object) -> Mutation:
    if not isinstance(item, dict) or set(item) != _MUTATION_FIELDS:
        raise PolicyError("each drill mutation needs exactly path, find and replace")
    if not all(isinstance(value, str) and value for value in item.values()):
        raise PolicyError("drill fields must be non-empty strings")
    if item["find"] == item["replace"]:
        raise PolicyError(f"drill for {proposition} changes nothing")
    try:
        path_in_fleet = validate_repo_relative_path(item["path"])
    except UnsafePathError as exc:
        raise PolicyError("drill path must stay inside the fleet checkout") from exc
    return Mutation(path_in_fleet, item["find"], item["replace"])


def load_drills(path: Path) -> tuple[Drill, ...]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = document.get("drills") if isinstance(document, dict) else None
    if not isinstance(raw, list) or not raw or len(raw) > _MAX_DRILLS:
        raise PolicyError("drill file must list between 1 and 64 drills")
    drills = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("proposition"), str):
            raise PolicyError("each drill needs a proposition")
        proposition = item["proposition"]
        expect = item.pop("expect", "divergent")
        if expect not in _EXPECTATIONS:
            raise PolicyError("drill expect must be divergent or declared_unverified")
        if set(item) == {"proposition", "variants"}:
            variants = item["variants"]
            if not isinstance(variants, list) or not 2 <= len(variants) <= _MAX_VARIANTS:
                raise PolicyError("drill variants must list between 2 and 8 mutations")
            mutations = [_mutation(proposition, variant) for variant in variants]
        elif set(item) == {"proposition", *_MUTATION_FIELDS}:
            mutations = [_mutation(proposition, {k: item[k] for k in _MUTATION_FIELDS})]
        else:
            raise PolicyError(
                "each drill needs exactly proposition, path, find and replace, or variants"
            )
        first, *rest = mutations
        drills.append(
            Drill(proposition, first.path, first.find, first.replace, tuple(rest), expect)
        )
    return tuple(drills)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv, paths from trusted drills
        ["git", "-c", "user.name=drill", "-c", "user.email=drill@invalid", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _statuses(report_dir: Path) -> dict[str, str]:
    report = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    return {
        str(item["proposition_id"]): str(item["status"]) for item in report["intent_evaluations"]
    }


def run_drills(
    checkout: Path,
    drills: tuple[Drill, ...],
    review: Callable[[Path, str, Path], None],
    work_dir: Path,
) -> tuple[DrillResult, ...]:
    """`review(worktree, sha, output_dir)` runs one ordinary review."""
    base_sha = _git(checkout, "rev-parse", "HEAD")
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir) as scratch:
        worktree = Path(scratch) / "fleet"
        _git(checkout, "worktree", "add", "--quiet", "--detach", str(worktree), base_sha)
        try:
            review(worktree, base_sha, work_dir / "base")
            base = _statuses(work_dir / "base")
            results = []
            for index, drill in enumerate(drills):
                _git(worktree, "reset", "--quiet", "--hard", base_sha)
                applied, text = None, ""
                for mutation in drill.mutations():
                    target = worktree / mutation.path
                    # The fleet is untrusted: a tracked symlink must not redirect a
                    # drill's write outside the throwaway worktree.
                    inside = not target.is_symlink() and target.resolve().is_relative_to(
                        worktree.resolve()
                    )
                    try:
                        text = (
                            target.read_text(encoding="utf-8")
                            if inside and target.is_file()
                            else ""
                        )
                    except UnicodeDecodeError:
                        text = ""  # the fleet changed the file beyond what the drill targets
                    if mutation.find in text:
                        applied = mutation
                        break
                if applied is None:
                    results.append(DrillResult(drill, "stale"))
                    continue
                if base.get(drill.proposition) == "divergent":
                    results.append(DrillResult(drill, "already_divergent", applied))
                    continue
                target = worktree / applied.path
                target.write_text(text.replace(applied.find, applied.replace), encoding="utf-8")
                _git(worktree, "commit", "--quiet", "--all", "-m", f"drill {drill.proposition}")
                output = work_dir / f"drill-{index:02d}-{drill.proposition}"
                review(worktree, _git(worktree, "rev-parse", "HEAD"), output)
                # An unverified result proves nothing unless the fleet held a proof.
                caught = (
                    _statuses(output).get(drill.proposition)
                    == drill.expect
                    != base.get(drill.proposition)
                )
                results.append(DrillResult(drill, "caught" if caught else "missed", applied))
        finally:
            _git(checkout, "worktree", "remove", "--force", str(worktree))
    return tuple(results)


def to_markdown(results: tuple[DrillResult, ...]) -> str:
    symbol = {
        "caught": "caught",
        "missed": "**MISSED**",
        "stale": "**stale drill**",
        "already_divergent": "already divergent on the fleet",
    }
    lines = [
        "## Check drills",
        "",
        "| Proposition | File | Result |",
        "|---|---|---|",
        *(
            f"| `{r.drill.proposition}` | `{(r.applied or r.drill).path}` | {symbol[r.outcome]} |"
            for r in results
        ),
        "",
    ]
    return "\n".join(lines)


def drills_passed(results: tuple[DrillResult, ...]) -> bool:
    return all(r.outcome in {"caught", "already_divergent"} for r in results)
