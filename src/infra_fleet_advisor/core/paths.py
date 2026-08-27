import posixpath

from infra_fleet_advisor.core.errors import UnsafePathError


def validate_repo_relative_path(raw: str) -> str:
    if not raw or not raw.strip():
        raise UnsafePathError("empty path")
    candidate = raw.replace("\\", "/")
    if candidate.startswith("/") or (len(candidate) > 1 and candidate[1] == ":"):
        raise UnsafePathError(f"absolute path not allowed: {raw!r}")
    normalized = posixpath.normpath(candidate)
    if normalized in (".", "..") or normalized.startswith(("../", "/")):
        raise UnsafePathError(f"path escapes source root: {raw!r}")
    return normalized
