"""Render a fleet deployment profile the way Flux would, without running anything.

A profile root (`k8s/clusters/<profile>`) is a kustomization of Flux
`Kustomization` objects; each names a `spec.path` overlay that is itself built
with kustomize. This module implements the closed subset the fleet uses —
`resources` (tracked local files and directories), inline JSON6902 `patches`
targeted by kind and name, and `images` — in pure Python. Anything outside that
subset, a remote base, a path leaving the checkout or an untracked file makes
the render incomplete rather than guessed. Flux `${VAR}` substitutions stay
literal, and HelmRelease chart output is not rendered.
"""

import copy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from infra_fleet_advisor.core.limits import ExecutionLimits

_KUSTOMIZATION_KEYS = {"apiVersion", "kind", "resources", "patches", "images"}
_FLUX_KUSTOMIZATION = "kustomize.toolkit.fluxcd.io/"
_MAX_DEPTH = 8
_MAX_RESOURCES = 2000


@dataclass(frozen=True, slots=True)
class RenderedResource:
    source_path: str
    body: dict[str, Any]


@dataclass(slots=True)
class ProfileRender:
    profile: str
    resources: list[RenderedResource] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.gaps


class _Incomplete(Exception):
    pass


class _Renderer:
    def __init__(
        self,
        checkout_root: Path,
        limits: ExecutionLimits,
        tracked_paths: frozenset[str] | None,
    ) -> None:
        self.root = checkout_root
        self.real = checkout_root.resolve()
        self.limits = limits
        self.tracked = tracked_paths
        self.files_read = 0

    def _read(self, rel_path: str) -> str:
        path = self.root / rel_path
        if self.tracked is not None and rel_path not in self.tracked:
            raise _Incomplete(f"{rel_path} is not part of the verified commit")
        if path.is_symlink() or not path.resolve().is_relative_to(self.real):
            raise _Incomplete(f"{rel_path} is not a regular in-checkout file")
        if not path.is_file() or path.stat().st_size > self.limits.max_manifest_file_bytes:
            raise _Incomplete(f"{rel_path} is unreadable or too large")
        self.files_read += 1
        if self.files_read > self.limits.max_manifest_files:
            raise _Incomplete("manifest file limit reached")
        return path.read_text(encoding="utf-8")

    def _local(self, base: str, reference: str) -> str:
        if "://" in reference or reference.startswith(("github.com", "git@")):
            raise _Incomplete(f"remote resource {reference} is not rendered")
        joined = (PurePosixPath(base) / reference).as_posix()
        parts: list[str] = []
        for part in PurePosixPath(joined).parts:
            if part == "..":
                if not parts:
                    raise _Incomplete(f"{reference} leaves the checkout")
                parts.pop()
            elif part != ".":
                parts.append(part)
        return "/".join(parts)

    def build(self, directory: str, depth: int = 0) -> list[RenderedResource]:
        if depth > _MAX_DEPTH:
            raise _Incomplete("kustomization nesting limit reached")
        rel_path = f"{directory}/kustomization.yaml"
        document = yaml.safe_load(self._read(rel_path))
        if not isinstance(document, dict) or set(document) - _KUSTOMIZATION_KEYS:
            raise _Incomplete(f"{rel_path} uses unsupported kustomize fields")
        output: list[RenderedResource] = []
        for reference in document.get("resources") or []:
            if not isinstance(reference, str):
                raise _Incomplete(f"{rel_path} has a malformed resource")
            target = self._local(directory, reference)
            if (self.root / target).is_dir():
                output.extend(self.build(target, depth + 1))
            else:
                for body in yaml.safe_load_all(self._read(target)):
                    if isinstance(body, dict):
                        output.append(RenderedResource(target, body))
            if len(output) > _MAX_RESOURCES:
                raise _Incomplete("rendered resource limit reached")
        for patch in document.get("patches") or []:
            self._apply(patch, output, rel_path)
        # `images` rewrites container image references only; no evaluated fact
        # depends on the image, so it needs no rendering here.
        return output

    def _apply(self, patch: Any, resources: list[RenderedResource], rel_path: str) -> None:
        if not isinstance(patch, dict) or set(patch) != {"target", "patch"}:
            raise _Incomplete(f"{rel_path} uses an unsupported patch form")
        target, operations = patch["target"], yaml.safe_load(patch["patch"])
        if not isinstance(target, dict) or set(target) - {"kind", "name", "namespace"}:
            raise _Incomplete(f"{rel_path} uses an unsupported patch target")
        if not isinstance(operations, list):
            raise _Incomplete(f"{rel_path} uses a strategic-merge patch")
        matched = 0
        for index, resource in enumerate(resources):
            metadata = resource.body.get("metadata") or {}
            if all(
                (resource.body.get("kind") if key == "kind" else metadata.get(key)) == value
                for key, value in target.items()
            ):
                body = copy.deepcopy(resource.body)
                for operation in operations:
                    _json_patch(body, operation, rel_path)
                resources[index] = RenderedResource(resource.source_path, body)
                matched += 1
        if not matched:
            raise _Incomplete(f"{rel_path} patch matches no resource")


def _json_patch(document: dict[str, Any], operation: Any, rel_path: str) -> None:
    if not isinstance(operation, dict) or operation.get("op") not in {"add", "replace", "remove"}:
        raise _Incomplete(f"{rel_path} uses an unsupported patch operation")
    path = operation.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise _Incomplete(f"{rel_path} has a malformed patch path")
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]
    parent: Any = document
    for token in tokens[:-1]:
        try:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise _Incomplete(f"{rel_path} patch path {path} does not exist") from exc
    last, op = tokens[-1], operation["op"]
    try:
        if isinstance(parent, list):
            if op == "add" and last == "-":
                parent.append(operation.get("value"))
            elif op == "add":
                parent.insert(int(last), operation.get("value"))
            elif op == "replace":
                parent[int(last)] = operation.get("value")
            else:
                parent.pop(int(last))
        elif isinstance(parent, dict):
            if op == "replace" and last not in parent:
                raise KeyError(last)
            if op == "remove":
                del parent[last]
            else:
                parent[last] = operation.get("value")
        else:
            raise TypeError(path)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise _Incomplete(f"{rel_path} patch {op} {path} cannot apply") from exc


def render_profile(
    checkout_root: Path,
    profile: str,
    limits: ExecutionLimits,
    tracked_paths: frozenset[str] | None = None,
) -> ProfileRender:
    """Everything the profile's Flux Kustomizations would apply, from Git alone."""
    render = ProfileRender(profile)
    renderer = _Renderer(checkout_root, limits, tracked_paths)
    try:
        roots = renderer.build(f"k8s/clusters/{profile}")
    except (_Incomplete, yaml.YAMLError, OSError, UnicodeError) as exc:
        render.gaps.append(str(exc) if isinstance(exc, _Incomplete) else type(exc).__name__)
        return render
    for flux in roots:
        body = flux.body
        if not str(body.get("apiVersion", "")).startswith(_FLUX_KUSTOMIZATION):
            render.resources.append(flux)
            continue
        path = str((body.get("spec") or {}).get("path", ""))
        try:
            overlay = renderer._local("", path.removeprefix("./"))
            render.resources.extend(renderer.build(overlay))
        except (_Incomplete, yaml.YAMLError, OSError, UnicodeError) as exc:
            render.gaps.append(str(exc) if isinstance(exc, _Incomplete) else type(exc).__name__)
    return render
