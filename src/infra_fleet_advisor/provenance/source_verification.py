import subprocess
from dataclasses import dataclass
from pathlib import Path

from infra_fleet_advisor.core.errors import ProvenanceError


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Public, machine-path-free record of the verified source. `checkout_path`
    is deliberately not a field here — it must never leave `runtime`."""

    commit_sha: str
    source_label: str


def _git(checkout_path: Path, *args: str) -> str:
    # fixed argv, no shell, no config-supplied commands. -c core.fsmonitor=false
    # stops a checkout with an attacker-controlled .git/config from running an
    # arbitrary hook as this process via `git status`.
    result = subprocess.run(  # noqa: S603
        ["git", "-c", "core.fsmonitor=false", "-C", str(checkout_path), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # git's stderr can embed the local checkout path (e.g. "fatal: cannot
        # change to '<path>'") — redact it so it never leaves this module.
        sanitized = result.stderr.strip().replace(str(checkout_path), "<checkout>")[:200]
        raise ProvenanceError(f"git {args[0]} failed: {sanitized}")
    return result.stdout.strip()


def list_tracked_paths(checkout_path: Path, subdir: str) -> frozenset[str]:
    """Files git actually tracks at HEAD under `subdir` — the ground truth
    for what's "part of the verified commit". A .gitignore'd file sitting on
    disk inside the checkout is invisible to `git status`'s dirty-checkout
    check (ignored files aren't reported as untracked) but is NOT part of
    the verified snapshot; collectors must not treat it as evidence."""
    output = _git(checkout_path, "ls-tree", "-r", "--name-only", "HEAD", "--", subdir)
    return frozenset(line for line in output.splitlines() if line)


def verify_snapshot(checkout_path: Path, expected_sha: str, source_label: str) -> SourceProvenance:
    if not (checkout_path / ".git").exists():
        raise ProvenanceError("checkout_path is not a git repository")

    actual_sha = _git(checkout_path, "rev-parse", "HEAD")
    if actual_sha != expected_sha:
        raise ProvenanceError("sha_mismatch")

    status = _git(checkout_path, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        dirty_count = len(status.splitlines())
        raise ProvenanceError(f"dirty_checkout: {dirty_count} changed/untracked path(s)")

    return SourceProvenance(commit_sha=actual_sha, source_label=source_label)
