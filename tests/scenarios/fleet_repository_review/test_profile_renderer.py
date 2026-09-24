from pathlib import Path

from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.scenarios.fleet_repository_review.profile_renderer import (
    render_profile,
)

LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)
KUSTOMIZATION = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
FLUX = (
    "apiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\n"
    "metadata: {name: apps, namespace: flux-system}\n"
    "spec: {path: ./k8s/overlay, sourceRef: {kind: GitRepository, name: flux-system}}\n"
)
CONFIG = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: c}\ndata: {a: '1', list: [x]}\n"


def _profile(tmp_path: Path, overlay: str, extra: dict[str, str] | None = None):
    files = {
        "k8s/clusters/p/kustomization.yaml": KUSTOMIZATION + "resources: [apps.yaml]\n",
        "k8s/clusters/p/apps.yaml": FLUX,
        "k8s/base/kustomization.yaml": KUSTOMIZATION + "resources: [config.yaml]\n",
        "k8s/base/config.yaml": CONFIG,
        "k8s/overlay/kustomization.yaml": KUSTOMIZATION + overlay,
        **(extra or {}),
    }
    for rel_path, text in files.items():
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return render_profile(tmp_path, "p", LIMITS)


def test_json6902_patches_apply_to_the_rendered_base(tmp_path: Path) -> None:
    render = _profile(
        tmp_path,
        "resources: [../base]\npatches:\n  - target: {kind: ConfigMap, name: c}\n"
        "    patch: |-\n      - {op: replace, path: /data/a, value: '2'}\n"
        "      - {op: add, path: /data/list/-, value: y}\n"
        "      - {op: add, path: /data/b~1c, value: z}\n",
    )

    assert render.complete, render.gaps
    [config] = [r for r in render.resources if r.body["kind"] == "ConfigMap"]
    assert config.source_path == "k8s/base/config.yaml"
    assert config.patch_path == "k8s/overlay/kustomization.yaml"
    assert config.body["data"] == {"a": "2", "list": ["x", "y"], "b/c": "z"}
    # The base file on disk is untouched.
    assert "'1'" in (tmp_path / "k8s/base/config.yaml").read_text(encoding="utf-8")


def test_unsupported_or_unsafe_inputs_make_the_render_incomplete(tmp_path: Path) -> None:
    for overlay, gap in (
        ("resources: [https://example.com/base]\n", "remote resource"),
        ("resources: [../../../outside]\n", "leaves the checkout"),
        ("resources: [../base]\nnamePrefix: x-\n", "unsupported kustomize fields"),
        (
            "resources: [../base]\npatches:\n  - target: {kind: ConfigMap, name: c}\n"
            "    patch: 'metadata: {labels: {a: b}}'\n",
            "strategic-merge",
        ),
        (
            "resources: [../base]\npatches:\n  - target: {kind: Secret, name: s}\n"
            "    patch: '[{op: remove, path: /data}]'\n",
            "matches no resource",
        ),
    ):
        render = _profile(tmp_path, overlay)
        assert not render.complete, overlay
        assert any(gap in reason for reason in render.gaps), (overlay, render.gaps)


def test_untracked_files_are_not_rendered(tmp_path: Path) -> None:
    _profile(tmp_path, "resources: [../base]\n")
    tracked = frozenset(
        {
            "k8s/clusters/p/kustomization.yaml",
            "k8s/clusters/p/apps.yaml",
            "k8s/overlay/kustomization.yaml",
            "k8s/base/kustomization.yaml",
        }
    )

    render = render_profile(tmp_path, "p", LIMITS, tracked)

    assert not render.complete
    assert "not part of the verified commit" in render.gaps[0]


def test_malformed_and_unsafe_flux_or_kustomize_input_is_incomplete(tmp_path: Path) -> None:
    for overlay, gap in (
        (
            "resources: [../base]\npatches:\n  - target: {kind: ConfigMap, name: c}\n"
            "    patch: [1, 2]\n",
            "unsupported patch form",
        ),
        ("resources: 7\n", "malformed resources"),
    ):
        render = _profile(tmp_path, overlay)
        assert any(gap in reason for reason in render.gaps), (overlay, render.gaps)

    for spec, gap in (
        (
            "{path: ./k8s/overlay, targetNamespace: other, sourceRef: {kind: GitRepository, "
            "name: flux-system}}",
            "fields that change",
        ),
        (
            "{path: ./k8s/overlay, sourceRef: {kind: GitRepository, name: elsewhere}}",
            "source other than this repository",
        ),
    ):
        flux = FLUX.replace(
            "spec: {path: ./k8s/overlay, sourceRef: {kind: GitRepository, name: flux-system}}",
            f"spec: {spec}",
        )
        render = _profile(tmp_path, "resources: [../base]\n", {"k8s/clusters/p/apps.yaml": flux})
        assert any(gap in reason for reason in render.gaps), (spec, render.gaps)


def test_only_explicit_checkout_mirrors_are_rendered(tmp_path: Path) -> None:
    flux = FLUX.replace("name: flux-system", "name: local-source")
    source_path = "platform/local/source.yaml"
    source = (
        "apiVersion: source.toolkit.fluxcd.io/v1\nkind: GitRepository\n"
        "metadata:\n  name: local-source\n  namespace: flux-system\n"
        "spec: {url: https://example.com/somewhere-else.git}\n"
    )
    _profile(
        tmp_path,
        "resources: [../base]\n",
        {"k8s/clusters/p/apps.yaml": flux, source_path: source},
    )
    tracked = frozenset(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()
    )

    untrusted = render_profile(tmp_path, "p", LIMITS, tracked)

    assert not untrusted.complete
    assert "source other than this repository" in untrusted.gaps[0]

    annotated = source.replace(
        "  name: local-source\n",
        '  name: local-source\n  annotations:\n    infra-fleet.io/checkout-mirror: "true"\n',
    )
    (tmp_path / source_path).write_text(annotated, encoding="utf-8")

    trusted = render_profile(tmp_path, "p", LIMITS, tracked)

    assert trusted.complete, trusted.gaps
    assert [resource.body["kind"] for resource in trusted.resources] == ["ConfigMap"]


def test_a_mirror_is_trusted_by_namespace_and_name_not_name_alone(tmp_path: Path) -> None:
    mirror = (
        "apiVersion: source.toolkit.fluxcd.io/v1\nkind: GitRepository\n"
        "metadata:\n  name: apps-source\n  namespace: team-a\n"
        '  annotations:\n    infra-fleet.io/checkout-mirror: "true"\n'
        "spec: {url: https://example.com/checkout.git}\n"
    )
    for source_ref, trusted in (
        ("{kind: GitRepository, name: apps-source, namespace: team-a}", True),
        # Same name, another namespace: an unrelated, unannotated source.
        ("{kind: GitRepository, name: apps-source, namespace: team-b}", False),
        # Omitted namespace resolves to the Kustomization's own (flux-system).
        ("{kind: GitRepository, name: apps-source}", False),
        ("{kind: GitRepository, name: flux-system, namespace: team-b}", False),
    ):
        flux = FLUX.replace(
            "sourceRef: {kind: GitRepository, name: flux-system}", f"sourceRef: {source_ref}"
        )
        render = _profile(
            tmp_path,
            "resources: [../base]\n",
            {"k8s/clusters/p/apps.yaml": flux, "platform/mirror.yaml": mirror},
        )
        assert render.complete is trusted, (source_ref, render.gaps)


def test_nested_flux_kustomizations_and_alternate_filenames_are_followed(tmp_path: Path) -> None:
    child = FLUX.replace("name: apps", "name: child").replace("k8s/overlay", "k8s/child")
    render = _profile(
        tmp_path,
        "resources: [child.yaml]\n",
        {
            "k8s/overlay/child.yaml": child,
            "k8s/child/kustomization.yml": KUSTOMIZATION + "resources: [../base]\n",
        },
    )

    assert render.complete, render.gaps
    assert [r.body["kind"] for r in render.resources] == ["ConfigMap"]


def test_policy_exclusions_stop_the_render(tmp_path: Path) -> None:
    from infra_fleet_advisor.scenarios.fleet_repository_review.profile_renderer import (
        render_profiles,
    )

    _profile(tmp_path, "resources: [../base]\n")
    [render] = render_profiles(tmp_path, ["p"], LIMITS, excluded_paths=frozenset({"k8s/overlay"}))

    assert any("excluded by policy" in gap for gap in render.gaps)
