from types import SimpleNamespace

import pytest

from sentinel.llm import (
    TOOL_NAME,
    AnthropicProvider,
    BedrockProvider,
    Review,
    ReviewParseError,
    ReviewRequest,
    get_provider,
    parse_anthropic_message,
    parse_converse_response,
)
from sentinel.risk import RiskLevel, assess
from tests.conftest import scenario

PAYLOAD = {
    "risk_level": "HIGH",
    "summary": "Opens SSH to the world.",
    "blast_radius": ["AppSecurityGroup"],
    "data_loss_risks": [],
    "rollback_plan": ["Revert the rule"],
    "pre_deploy_checks": "Single string is coerced to a list",
    "post_deploy_verification": ["Port scan"],
}


def converse_response(payload):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"text": "Calling the tool."},
                    {"toolUse": {"toolUseId": "t1", "name": TOOL_NAME, "input": payload}},
                ],
            }
        },
        "stopReason": "tool_use",
    }


class FakeBedrockClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return converse_response(self.payload)


def request():
    cs = scenario("03-open-ssh-security-group")
    return ReviewRequest(system="sys", prompt="prompt", assessment=assess(cs), stack_name="s")


def test_parse_converse_tool_use():
    review = parse_converse_response(converse_response(PAYLOAD))
    assert review.risk_level is RiskLevel.HIGH
    assert review.pre_deploy_checks == ["Single string is coerced to a list"]


def test_parse_converse_without_tool_call():
    with pytest.raises(ReviewParseError, match=TOOL_NAME):
        parse_converse_response({"output": {"message": {"content": [{"text": "hi"}]}}})


def test_parse_converse_malformed():
    with pytest.raises(ReviewParseError):
        parse_converse_response({"nope": True})


def test_review_rejects_bad_level():
    with pytest.raises(ReviewParseError):
        Review.from_dict(dict(PAYLOAD, risk_level="SEVERE"))


def test_review_rejects_non_list():
    with pytest.raises(ReviewParseError):
        Review.from_dict(dict(PAYLOAD, rollback_plan={"a": 1}))


def test_bedrock_provider_forces_the_tool():
    client = FakeBedrockClient(PAYLOAD)
    provider = BedrockProvider(model_id="us.anthropic.test-model", client=client)
    review = provider.review(request())
    call = client.calls[0]
    assert call["modelId"] == "us.anthropic.test-model"
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert call["inferenceConfig"]["temperature"] == 0
    assert review.summary == "Opens SSH to the world."


def test_anthropic_provider_with_fake_client():
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input=PAYLOAD)
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="x"), block])

    provider = AnthropicProvider(
        model_id="claude-test", client=SimpleNamespace(messages=Messages())
    )
    review = provider.review(request())
    assert captured["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert review.risk_level is RiskLevel.HIGH


def test_parse_anthropic_without_tool_call():
    with pytest.raises(ReviewParseError):
        parse_anthropic_message(SimpleNamespace(content=[SimpleNamespace(type="text")]))


def test_get_provider_names():
    assert get_provider("mock").name == "mock"
    assert get_provider("none").name == "none"
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("gpt")


def test_anthropic_ignores_bedrock_style_model_ids(monkeypatch):
    captured = {}

    def fake_init(self, model_id=None, client=None, max_tokens=2000):
        captured["model_id"] = model_id

    monkeypatch.setattr(AnthropicProvider, "__init__", fake_init)
    get_provider("anthropic", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert captured["model_id"] is None
    get_provider("anthropic", "claude-opus-4-1")
    assert captured["model_id"] == "claude-opus-4-1"
