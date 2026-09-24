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
    "metadata: {name: apps}\nspec: {path: ./k8s/overlay}\n"
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
