from pathlib import Path

import pytest

from infra_fleet_advisor.core.errors import UnsafePathError
from infra_fleet_advisor.core.evidence import Evidence
from infra_fleet_advisor.scenarios.fleet_repository_review.concerns import (
    CONCERN_TRIVY_IGNORE_UNFIXED,
    CONCERN_WILDCARD_IAM_PERMISSIONS,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.remediation import (
    apply_patches,
    build_patches,
    patchable_concerns,
)

WORKFLOW = """\
      - name: Security scan (Trivy)
        uses: aquasecurity/trivy-action@0.33.1
        with:
          image-ref: app:latest
          severity: CRITICAL,HIGH
          exit-code: 1
          ignore-unfixed: true

  push:
"""


def _evidence(path: str = ".github/workflows/ci.yml") -> dict[str, Evidence]:
    ev = Evidence(
        evidence_id="e1",
        kind="gha_trivy_gate",
        source_path=path,
        locator="loc",
        excerpt="e",
        fact={"ignore_unfixed": True},
    )
    return {"e1": ev}


def _checkout(tmp_path: Path, body: str = WORKFLOW) -> Path:
    target = tmp_path / ".github" / "workflows"
    target.mkdir(parents=True)
    (target / "ci.yml").write_text(body, encoding="utf-8")
    return tmp_path


def _build(tmp_path: Path, concern: str = CONCERN_TRIVY_IGNORE_UNFIXED, **kw):
    return build_patches(
        checkout_root=_checkout(tmp_path),
        concern_key=concern,
        evidence_ids=("e1",),
        evidence_by_id=_evidence(),
        **kw,
    )


def test_removes_the_ignore_unfixed_entry(tmp_path: Path) -> None:
    patches = _build(tmp_path)

    assert len(patches) == 1
    assert "ignore-unfixed" not in patches[0].patched
    # Everything else in the step survives.
    assert "severity: CRITICAL,HIGH" in patches[0].patched
    assert "exit-code: 1" in patches[0].patched


def test_apply_writes_the_file(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    patches = build_patches(
        checkout_root=root,
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        evidence_ids=("e1",),
        evidence_by_id=_evidence(),
    )
    written = apply_patches(root, patches)

    assert written == (".github/workflows/ci.yml",)
    assert "ignore-unfixed" not in (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_concern_without_a_patcher_produces_nothing(tmp_path: Path) -> None:
    # Scoping a wildcard IAM policy needs to know which API calls the pipeline
    # makes. Guessing would be a confident, wrong, security-relevant change.
    assert _build(tmp_path, concern=CONCERN_WILDCARD_IAM_PERMISSIONS) == ()
    assert CONCERN_WILDCARD_IAM_PERMISSIONS not in patchable_concerns()


def test_already_fixed_file_yields_no_patch(tmp_path: Path) -> None:
    clean = WORKFLOW.replace("          ignore-unfixed: true\n", "")
    patches = build_patches(
        checkout_root=_checkout(tmp_path, clean),
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        evidence_ids=("e1",),
        evidence_by_id=_evidence(),
    )
    # Makes the command idempotent, and means a resolved finding is a no-op.
    assert patches == ()


def test_only_files_the_report_cites_are_touched(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    other = root / ".github" / "workflows" / "unreferenced.yml"
    other.write_text(WORKFLOW, encoding="utf-8")

    apply_patches(
        root,
        build_patches(
            checkout_root=root,
            concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
            evidence_ids=("e1",),
            evidence_by_id=_evidence(),
        ),
    )

    # Same pattern, never cited as evidence, so out of bounds.
    assert "ignore-unfixed: true" in other.read_text(encoding="utf-8")


def test_unresolvable_evidence_id_is_skipped(tmp_path: Path) -> None:
    patches = build_patches(
        checkout_root=_checkout(tmp_path),
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        evidence_ids=("does-not-exist",),
        evidence_by_id=_evidence(),
    )
    assert patches == ()


def test_evidence_path_escaping_the_checkout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        build_patches(
            checkout_root=_checkout(tmp_path),
            concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
            evidence_ids=("e1",),
            evidence_by_id=_evidence("../../etc/passwd"),
        )


def test_symlinked_evidence_path_is_not_written(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    outside = tmp_path.parent / "outside.yml"
    outside.write_text(WORKFLOW, encoding="utf-8")
    link = root / ".github" / "workflows" / "linked.yml"
    link.symlink_to(outside)

    # A tracked path resolving outside the checkout is an anomaly, not something
    # to skip quietly — the same stance the Terraform collector takes.
    with pytest.raises(UnsafePathError):
        build_patches(
            checkout_root=root,
            concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
            evidence_ids=("e1",),
            evidence_by_id=_evidence(".github/workflows/linked.yml"),
        )

    assert "ignore-unfixed: true" in outside.read_text(encoding="utf-8")


def test_value_inside_a_longer_expression_is_left_alone(tmp_path: Path) -> None:
    body = "        run: trivy image --ignore-unfixed: true-ish thing\n"
    patches = build_patches(
        checkout_root=_checkout(tmp_path, body),
        concern_key=CONCERN_TRIVY_IGNORE_UNFIXED,
        evidence_ids=("e1",),
        evidence_by_id=_evidence(),
    )
    assert patches == ()
