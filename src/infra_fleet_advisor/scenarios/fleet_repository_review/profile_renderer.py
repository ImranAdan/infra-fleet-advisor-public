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
KUSTOMIZATION_FILES = ("kustomization.yaml", "kustomization.yml", "Kustomization")
_FLUX_KUSTOMIZATION = "kustomize.toolkit.fluxcd.io/"
# Flux Kustomization fields that do not change what is applied. Anything else
# (patches, targetNamespace, components, name affixes, images, commonMetadata)
# would, and makes the render incomplete.
_FLUX_SPEC_KEYS = {
    "interval",
    "retryInterval",
    "timeout",
    "path",
    "prune",
    "sourceRef",
    "wait",
    "dependsOn",
    "healthChecks",
    "postBuild",
    "force",
    "suspend",
    "serviceAccountName",
}
# Flux's bootstrap source is the repository Flux was bootstrapped from.
_BOOTSTRAP_SOURCE = "flux-system"
_CHECKOUT_MIRROR_ANNOTATION = "infra-fleet.io/checkout-mirror"
_MAX_DEPTH = 8
_MAX_RESOURCES = 2000
_MAX_SOURCE_SCAN_FILES = 1000


@dataclass(frozen=True, slots=True)
class RenderedResource:
    source_path: str
    body: dict[str, Any]
    patch_path: str | None = None


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
        excluded_paths: frozenset[str] = frozenset(),
    ) -> None:
        self.root = checkout_root
        self.real = checkout_root.resolve()
        self.limits = limits
        self.tracked = tracked_paths
        self.excluded = excluded_paths
        # One budget of distinct files for every profile rendered here; profiles
        # share their base, so a cached re-read costs nothing.
        self.cache: dict[str, str] = {}

    def _read(self, rel_path: str) -> str:
        if rel_path in self.cache:
            return self.cache[rel_path]
        path = self.root / rel_path
        if any(rel_path == ex or rel_path.startswith(f"{ex}/") for ex in self.excluded):
            raise _Incomplete(f"{rel_path} is excluded by policy")
        if self.tracked is not None and rel_path not in self.tracked:
            raise _Incomplete(f"{rel_path} is not part of the verified commit")
        if path.is_symlink() or not path.resolve().is_relative_to(self.real):
            raise _Incomplete(f"{rel_path} is not a regular in-checkout file")
        if not path.is_file() or path.stat().st_size > self.limits.max_manifest_file_bytes:
            raise _Incomplete(f"{rel_path} is unreadable or too large")
        if len(self.cache) >= self.limits.max_manifest_files:
            raise _Incomplete("manifest file limit reached")
        self.cache[rel_path] = path.read_text(encoding="utf-8")
        return self.cache[rel_path]

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
        names = [name for name in KUSTOMIZATION_FILES if (self.root / directory / name).is_file()]
        if len(names) != 1:
            raise _Incomplete(f"{directory} has no single kustomization file")
        rel_path = f"{directory}/{names[0]}"
        document = yaml.safe_load(self._read(rel_path))
        if not isinstance(document, dict) or set(document) - _KUSTOMIZATION_KEYS:
            raise _Incomplete(f"{rel_path} uses unsupported kustomize fields")
        if not isinstance(document.get("resources") or [], list) or not isinstance(
            document.get("patches") or [], list
        ):
            raise _Incomplete(f"{rel_path} has malformed resources or patches")
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
        if (
            not isinstance(patch, dict)
            or set(patch) != {"target", "patch"}
            or not isinstance(patch["patch"], str)
        ):
            raise _Incomplete(f"{rel_path} uses an unsupported patch form")
        target, operations = patch["target"], yaml.safe_load(patch["patch"])
        if not isinstance(target, dict) or set(target) - {"kind", "name", "namespace"}:
            raise _Incomplete(f"{rel_path} uses an unsupported patch target")
        if not isinstance(operations, list):
            raise _Incomplete(f"{rel_path} uses a strategic-merge patch")
        matched = 0
        for index, resource in enumerate(resources):
            metadata = resource.body.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise _Incomplete(f"{resource.source_path} has malformed metadata")
            if all(
                (resource.body.get("kind") if key == "kind" else metadata.get(key)) == value
                for key, value in target.items()
            ):
                body = copy.deepcopy(resource.body)
                for operation in operations:
                    _json_patch(body, operation, rel_path)
                resources[index] = RenderedResource(resource.source_path, body, rel_path)
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


def _declared_sources(renderer: _Renderer) -> set[str]:
    """GitRepository sources explicitly declared as mirrors of the checkout."""
    names = {_BOOTSTRAP_SOURCE}
    tracked = renderer.tracked or frozenset()
    candidates = [path for path in sorted(tracked) if path.endswith((".yaml", ".yml"))]
    # A substring test precedes any parse, so this scan has its own, larger
    # bound. An unscanned file can only omit a source, which makes a render
    # incomplete rather than wrongly complete.
    for rel_path in candidates[:_MAX_SOURCE_SCAN_FILES]:
        path = renderer.root / rel_path
        try:
            if path.stat().st_size > renderer.limits.max_manifest_file_bytes:
                continue
            text = path.read_text(encoding="utf-8")
            if "kind: GitRepository" not in text:
                continue
            for body in yaml.safe_load_all(text):
                if isinstance(body, dict) and body.get("kind") == "GitRepository":
                    metadata = body.get("metadata")
                    if not isinstance(metadata, dict):
                        continue
                    annotations = metadata.get("annotations")
                    name = metadata.get("name")
                    if (
                        isinstance(annotations, dict)
                        and annotations.get(_CHECKOUT_MIRROR_ANNOTATION) == "true"
                        and isinstance(name, str)
                    ):
                        names.add(name)
        except (OSError, UnicodeError, yaml.YAMLError, AttributeError):
            continue
    return names


def _flux_path(body: dict[str, Any], sources: set[str]) -> str:
    """The local overlay a Flux Kustomization applies, or _Incomplete."""
    spec = body.get("spec")
    if not isinstance(spec, dict) or set(spec) - _FLUX_SPEC_KEYS:
        raise _Incomplete("a Flux Kustomization uses fields that change what it applies")
    post_build = spec.get("postBuild") or {}
    if not isinstance(post_build, dict) or set(post_build) - {"substitute", "substituteFrom"}:
        raise _Incomplete("a Flux Kustomization uses unsupported postBuild options")
    source = spec.get("sourceRef")
    if (
        not isinstance(source, dict)
        or source.get("kind") != "GitRepository"
        or source.get("name") not in sources
    ):
        raise _Incomplete("a Flux Kustomization reads a source other than this repository")
    path = spec.get("path")
    if not isinstance(path, str):
        raise _Incomplete("a Flux Kustomization has no path")
    return path.removeprefix("./")


def render_profiles(
    checkout_root: Path,
    profiles: list[str],
    limits: ExecutionLimits,
    tracked_paths: frozenset[str] | None = None,
    excluded_paths: frozenset[str] = frozenset(),
) -> list[ProfileRender]:
    """Render every profile against one shared file budget."""
    renderer = _Renderer(checkout_root, limits, tracked_paths, excluded_paths)
    sources = _declared_sources(renderer)
    return [_render(renderer, profile, sources) for profile in profiles]


def render_profile(
    checkout_root: Path,
    profile: str,
    limits: ExecutionLimits,
    tracked_paths: frozenset[str] | None = None,
) -> ProfileRender:
    return render_profiles(checkout_root, [profile], limits, tracked_paths)[0]


def _render(renderer: _Renderer, profile: str, sources: set[str]) -> ProfileRender:
    """Everything the profile's Flux Kustomizations would apply, from Git alone."""
    render = ProfileRender(profile)
    failures = (
        _Incomplete,
        yaml.YAMLError,
        OSError,
        UnicodeError,
        AttributeError,
        TypeError,
        ValueError,
        KeyError,
    )
    try:
        queue = [(flux, 0) for flux in renderer.build(f"k8s/clusters/{profile}")]
    except failures as exc:
        render.gaps.append(str(exc) if isinstance(exc, _Incomplete) else type(exc).__name__)
        return render
    # Flux Kustomizations can render further Flux Kustomizations; follow them.
    while queue:
        resource, depth = queue.pop(0)
        if not str(resource.body.get("apiVersion", "")).startswith(_FLUX_KUSTOMIZATION):
            render.resources.append(resource)
            continue
        try:
            if depth > _MAX_DEPTH:
                raise _Incomplete("Flux Kustomization nesting limit reached")
            overlay = renderer._local("", _flux_path(resource.body, sources))
            queue.extend((child, depth + 1) for child in renderer.build(overlay))
        except failures as exc:
            render.gaps.append(str(exc) if isinstance(exc, _Incomplete) else type(exc).__name__)
        if len(render.resources) + len(queue) > _MAX_RESOURCES:
            render.gaps.append("rendered resource limit reached")
            break
    return render
