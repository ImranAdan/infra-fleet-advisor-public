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
    # fixed argv, no shell, no config-supplied commands
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(checkout_path), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProvenanceError(f"git {args[0]} failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


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
