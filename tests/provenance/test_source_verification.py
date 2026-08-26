import pytest

from infra_fleet_advisor.core.errors import ProvenanceError
from infra_fleet_advisor.provenance.source_verification import verify_snapshot


def test_verifies_clean_checkout(git_checkout) -> None:
    repo, sha = git_checkout("oidc_and_trivy_good.yml")
    provenance = verify_snapshot(repo, sha, "infra-fleet-public")
    assert provenance.commit_sha == sha
    assert provenance.source_label == "infra-fleet-public"
    assert not hasattr(provenance, "checkout_path")


def test_sha_mismatch_rejected(git_checkout) -> None:
    repo, _sha = git_checkout("oidc_and_trivy_good.yml")
    with pytest.raises(ProvenanceError, match="sha_mismatch"):
        verify_snapshot(repo, "0" * 40, "infra-fleet-public")


def test_dirty_checkout_rejected(git_checkout) -> None:
    repo, sha = git_checkout("oidc_and_trivy_good.yml")
    (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="dirty_checkout"):
        verify_snapshot(repo, sha, "infra-fleet-public")


def test_non_git_directory_rejected(tmp_path) -> None:
    with pytest.raises(ProvenanceError):
        verify_snapshot(tmp_path, "0" * 40, "infra-fleet-public")


def test_provenance_never_carries_the_checkout_path(git_checkout) -> None:
    repo, sha = git_checkout("oidc_and_trivy_good.yml")
    provenance = verify_snapshot(repo, sha, "infra-fleet-public")
    assert str(repo) not in repr(provenance)
