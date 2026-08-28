import json
from pathlib import Path

import anthropic
import pytest

from infra_fleet_advisor.config.loader import load_policy
from infra_fleet_advisor.core.errors import SynthesisError
from infra_fleet_advisor.core.evidence import build_evidence
from infra_fleet_advisor.core.limits import ExecutionLimits
from infra_fleet_advisor.provenance.source_verification import verify_snapshot
from infra_fleet_advisor.scenarios.fleet_repository_review.anthropic_synthesis import (
    MODEL,
    AnthropicSynthesizer,
    build_prompt,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.constants import (
    EVIDENCE_KIND_IAM_WILDCARD,
    TAXONOMY,
)
from infra_fleet_advisor.scenarios.fleet_repository_review.review import run_review
from infra_fleet_advisor.scenarios.fleet_repository_review.synthesis import (
    EvidenceProjection,
    PolicyContext,
    StubSynthesizer,
)

try:  # the anthropic SDK's transport dependency, needed only to build request objects
    import httpx
except ImportError:  # pragma: no cover
    import httpx2 as httpx

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
POLICY_PATH = FIXTURES / "policies" / "valid_policy.yaml"
CONTEXT = PolicyContext(enabled_categories=frozenset({"security"}), max_recommendations=10)
LIMITS = ExecutionLimits(
    max_wall_seconds=60,
    max_model_calls=1,
    max_workflow_files=50,
    max_file_bytes=256 * 1024,
    max_recommendations=10,
)


def _recorded(name: str) -> str:
    return (FIXTURES / "model_responses" / f"{name}.json").read_text(encoding="utf-8")


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    """Stands in for client.messages. A recorded response's __EVIDENCE_ID__
    placeholder is filled from the evidence the prompt actually carried, so the
    fake cites what a well-behaved model would have been shown."""

    def __init__(self, outcome: str | Exception) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        prompt = kwargs["messages"][0]["content"]
        shown = json.loads(prompt.split("as JSON):\n", 1)[1])
        return _Message(self.outcome.replace("__EVIDENCE_ID__", shown[0]["evidence_id"]))


class _FakeClient:
    def __init__(self, outcome: str | Exception) -> None:
        self.messages = _FakeMessages(outcome)


def _iam_evidence(locator: str = "aws_iam_policy.github_actions"):
    return build_evidence(
        collector_id="terraform_iam",
        collector_version="1.0.0",
        kind=EVIDENCE_KIND_IAM_WILDCARD,
        source_path="infrastructure/permanent/github-oidc.tf",
        locator=locator,
        excerpt='Action = ["eks:*", "ec2:*"]\nResource = "*"',
        fact={"wildcard_actions": "eks:*, ec2:*", "wildcard_statement_count": 2},
    )


def _synthesize(outcome: str | Exception, evidence=None):
    client = _FakeClient(outcome)
    synth = AnthropicSynthesizer(client=client)
    projection = EvidenceProjection(
        policy_context=CONTEXT,
        evidence=(_iam_evidence(),) if evidence is None else evidence,
    )
    return synth.synthesize(projection), client


def test_recorded_response_maps_onto_the_candidate_contract() -> None:
    ev = _iam_evidence()
    response, client = _synthesize(_recorded("wildcard_iam_finding"), evidence=(ev,))

    assert len(response.recommendations) == 1
    rec = response.recommendations[0]
    assert rec.concern_key == "wildcard_iam_permissions"
    assert rec.category == "security"
    assert rec.priority == "critical"
    assert rec.evidence_ids == (ev.evidence_id,)
    assert 0.0 <= rec.confidence <= 1.0
    assert response.model_identifier == f"anthropic:{MODEL}"
    assert client.messages.calls[0]["model"] == MODEL


def test_empty_evidence_short_circuits_without_calling_the_model() -> None:
    response, client = _synthesize(_recorded("wildcard_iam_finding"), evidence=())

    assert response.recommendations == ()
    assert client.messages.calls == []


def test_response_schema_constrains_concern_key_category_and_priority() -> None:
    _response, client = _synthesize(_recorded("wildcard_iam_finding"))
    schema = client.messages.calls[0]["output_config"]["format"]["schema"]
    candidate = schema["properties"]["recommendations"]["items"]

    assert candidate["properties"]["concern_key"]["enum"] == [
        "static_aws_credentials_in_ci",
        "trivy_ignore_unfixed",
        "wildcard_iam_permissions",
    ]
    assert candidate["properties"]["category"]["enum"] == ["security"]
    assert candidate["properties"]["priority"]["enum"] == ["critical", "high", "medium", "low"]
    assert candidate["additionalProperties"] is False


@pytest.mark.parametrize(
    "body",
    ["not json at all", '{"unexpected": []}', '{"recommendations": [{"concern_key": "x"}]}'],
)
def test_unparseable_response_raises_rather_than_returning_nothing(body: str) -> None:
    # Degrading to an empty result here would mark every prior finding resolved.
    with pytest.raises(SynthesisError):
        _synthesize(body)


@pytest.mark.parametrize(
    "error",
    [
        anthropic.AnthropicError("api_key client option must be set"),
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")),
        anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")),
        # The SDK reports unresolvable authentication as a bare TypeError.
        TypeError("Could not resolve authentication method."),
    ],
)
def test_sdk_errors_become_synthesis_errors(error: Exception) -> None:
    with pytest.raises(SynthesisError):
        _synthesize(error)


def test_prompt_carries_every_evidence_id_and_renders_excerpts_as_json_data() -> None:
    first, second = _iam_evidence("policy.a"), _iam_evidence("policy.b")
    prompt = build_prompt(EvidenceProjection(policy_context=CONTEXT, evidence=(first, second)))

    assert first.evidence_id in prompt
    assert second.evidence_id in prompt
    # Excerpts are JSON-encoded, so repo content cannot break out of its
    # delimiter and be read as prompt structure.
    shown = json.loads(prompt.split("as JSON):\n", 1)[1])
    assert [e["evidence_id"] for e in shown] == [first.evidence_id, second.evidence_id]
    assert shown[0]["excerpt"] == first.excerpt
    assert "at most 10 recommendations" in prompt


def _review(repo: Path, sha: str, outcome: str):
    return run_review(
        checkout_root=repo,
        policy=load_policy(POLICY_PATH, TAXONOMY),
        source=verify_snapshot(repo, sha, "infra-fleet-public"),
        synthesizer=AnthropicSynthesizer(client=_FakeClient(outcome)),
        limits=LIMITS,
        prior=None,
        run_started_at="2026-08-26T00:00:00+00:00",
    )


def test_model_output_citing_an_invented_evidence_id_is_never_published(git_checkout) -> None:
    repo, sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    report = _review(repo, sha, _recorded("invented_evidence_id"))

    assert report.recommendations == ()


def test_off_taxonomy_concern_key_is_never_published(git_checkout) -> None:
    # The injection case: the model cites real evidence, so only the
    # concern-key check stands between an injected instruction and the report.
    repo, sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    report = _review(repo, sha, _recorded("injected_concern_key"))

    assert report.recommendations == ()


def test_fingerprint_matches_the_stub_for_the_same_finding(git_checkout) -> None:
    # Fingerprints key off category/concern/evidence, never model prose, so
    # lifecycle tracking survives swapping the synthesizer.
    repo, sha = git_checkout(terraform_files=("wildcard_iam_policy.tf",))
    from_model = _review(repo, sha, _recorded("wildcard_iam_finding"))
    from_stub = run_review(
        checkout_root=repo,
        policy=load_policy(POLICY_PATH, TAXONOMY),
        source=verify_snapshot(repo, sha, "infra-fleet-public"),
        synthesizer=StubSynthesizer(),
        limits=LIMITS,
        prior=None,
        run_started_at="2026-08-26T00:00:00+00:00",
    )

    assert from_model.recommendations[0].fingerprint == from_stub.recommendations[0].fingerprint
    assert from_model.recommendations[0].title != from_stub.recommendations[0].title
