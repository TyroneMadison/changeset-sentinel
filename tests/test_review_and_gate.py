from dataclasses import replace

import pytest

from sentinel.gate import decide
from sentinel.llm import Review, RuleBasedProvider
from sentinel.review import apply_floor, run_review
from sentinel.risk import RiskLevel
from tests.conftest import scenario


class FakeAIProvider:
    """Pretends to be a model that answers with a fixed risk level."""

    name = "fake-ai"
    model_id = "fake-model"
    is_ai = True

    def __init__(self, level: RiskLevel) -> None:
        self.level = level
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        base = RuleBasedProvider().review(request)
        return replace(base, risk_level=self.level, summary="model summary")


class BrokenProvider:
    name = "broken"
    model_id = "x"
    is_ai = True

    def review(self, request):
        raise TimeoutError("bedrock timed out")


def test_floor_rule_ai_cannot_lower():
    assert apply_floor(RiskLevel.CRITICAL, RiskLevel.LOW) is RiskLevel.CRITICAL


def test_floor_rule_ai_can_raise():
    assert apply_floor(RiskLevel.LOW, RiskLevel.HIGH) is RiskLevel.HIGH


def test_floor_rule_without_ai():
    assert apply_floor(RiskLevel.MEDIUM, None) is RiskLevel.MEDIUM


def test_review_keeps_floor_when_model_says_low():
    result = run_review(scenario("02-rds-engine-change"), FakeAIProvider(RiskLevel.LOW))
    assert result.final_level is RiskLevel.CRITICAL
    assert result.ai_level is RiskLevel.LOW
    assert result.floor_kept


def test_review_raises_when_model_says_higher():
    result = run_review(scenario("01-tag-change"), FakeAIProvider(RiskLevel.HIGH))
    assert result.final_level is RiskLevel.HIGH
    assert not result.floor_kept


def test_model_only_sees_redacted_prompt():
    provider = FakeAIProvider(RiskLevel.HIGH)
    run_review(scenario("04-iam-wildcard"), provider)
    assert "pk_demo_9f8e7d6c5b4a3210" not in provider.requests[0].prompt


def test_provider_failure_falls_back_and_still_gates():
    result = run_review(scenario("02-rds-engine-change"), BrokenProvider())
    assert result.ai_error.startswith("TimeoutError")
    assert result.provider == "fallback"
    assert result.final_level is RiskLevel.CRITICAL
    assert result.review.rollback_plan


def test_mock_provider_is_not_counted_as_ai():
    result = run_review(scenario("03-open-ssh-security-group"), RuleBasedProvider("mock"))
    assert not result.ai_used
    assert result.ai_level is None


@pytest.mark.parametrize(
    ("level", "threshold", "labels", "blocked"),
    [
        (RiskLevel.HIGH, "HIGH", [], True),
        (RiskLevel.CRITICAL, "HIGH", [], True),
        (RiskLevel.MEDIUM, "HIGH", [], False),
        (RiskLevel.CRITICAL, "HIGH", ["risk-accepted"], False),
        (RiskLevel.CRITICAL, "NONE", [], False),
        (RiskLevel.LOW, "low", [], True),
    ],
)
def test_gate(level, threshold, labels, blocked):
    assert decide(level, threshold, labels).blocked is blocked


def test_gate_records_approver_for_audit():
    decision = decide(RiskLevel.CRITICAL, "HIGH", {"risk-accepted"}, approver="reviewer1")
    assert decision.approved_by_label
    assert "@reviewer1" in decision.reason


def test_gate_custom_label():
    assert not decide(
        RiskLevel.HIGH, "HIGH", ["cab-approved"], approval_label="cab-approved"
    ).blocked


def test_review_dataclass_defaults():
    review = Review(risk_level=RiskLevel.LOW, summary="ok")
    assert review.rollback_plan == []
