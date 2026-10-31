"""LLM providers. Every provider returns the same structured Review.

bedrock    Claude on Amazon Bedrock through the Converse API, forced tool use.
anthropic  Claude through the Anthropic API, optional dependency, lazy import.
mock       Deterministic narrative built from the rules engine. Offline, used by
           tests and the demo.
none       Same deterministic narrative, labelled as no AI in the report.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from sentinel.risk import Assessment, RiskLevel

TOOL_NAME = "submit_review"
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

_LIST_FIELDS = (
    "blast_radius",
    "data_loss_risks",
    "rollback_plan",
    "pre_deploy_checks",
    "post_deploy_verification",
)

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk_level": {
            "type": "string",
            "enum": [level.name for level in RiskLevel],
            "description": "Your overall risk level. Never below the deterministic floor.",
        },
        "summary": {"type": "string", "description": "Two to four sentences for a reviewer."},
        "blast_radius": {"type": "array", "items": {"type": "string"}},
        "data_loss_risks": {"type": "array", "items": {"type": "string"}},
        "rollback_plan": {"type": "array", "items": {"type": "string"}},
        "pre_deploy_checks": {"type": "array", "items": {"type": "string"}},
        "post_deploy_verification": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["risk_level", "summary", *_LIST_FIELDS],
}


class ReviewParseError(ValueError):
    """The model answered, but not in the shape we asked for."""


@dataclass(frozen=True)
class Review:
    risk_level: RiskLevel
    summary: str
    blast_radius: list[str] = field(default_factory=list)
    data_loss_risks: list[str] = field(default_factory=list)
    rollback_plan: list[str] = field(default_factory=list)
    pre_deploy_checks: list[str] = field(default_factory=list)
    post_deploy_verification: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> Review:
        if not isinstance(data, dict):
            raise ReviewParseError("review payload is not an object")
        try:
            level = RiskLevel.parse(str(data["risk_level"]))
            summary = str(data["summary"]).strip()
        except (KeyError, ValueError) as exc:
            raise ReviewParseError(f"invalid review payload: {exc}") from exc
        lists: dict[str, list[str]] = {}
        for name in _LIST_FIELDS:
            value = data.get(name, [])
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                raise ReviewParseError(f"{name} must be a list of strings")
            lists[name] = [str(item).strip() for item in value if str(item).strip()]
        return cls(risk_level=level, summary=summary, **lists)


@dataclass(frozen=True)
class ReviewRequest:
    system: str
    prompt: str
    assessment: Assessment
    stack_name: str
    physical_ids: dict[str, str] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model_id: str | None
    is_ai: bool

    def review(self, request: ReviewRequest) -> Review: ...


def tool_spec_bedrock() -> dict[str, Any]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": TOOL_NAME,
                    "description": "Submit the structured change set review.",
                    "inputSchema": {"json": REVIEW_SCHEMA},
                }
            }
        ],
        "toolChoice": {"tool": {"name": TOOL_NAME}},
    }


def parse_converse_response(response: dict[str, Any]) -> Review:
    """Pull the forced tool call out of a Bedrock Converse response."""
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ReviewParseError("Converse response has no message content") from exc
    for block in content:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if tool_use and tool_use.get("name") == TOOL_NAME:
            return Review.from_dict(tool_use.get("input"))
    raise ReviewParseError(f"model did not call {TOOL_NAME}")


def parse_anthropic_message(message: Any) -> Review:
    """Pull the forced tool call out of an Anthropic Messages API response."""
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            return Review.from_dict(getattr(block, "input", None))
    raise ReviewParseError(f"model did not call {TOOL_NAME}")


class BedrockProvider:
    name = "bedrock"
    is_ai = True

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        client: Any = None,
        max_tokens: int = 2000,
    ) -> None:
        self.model_id = model_id or DEFAULT_BEDROCK_MODEL
        self.max_tokens = max_tokens
        if client is None:
            import boto3  # only needed when Bedrock is used

            client = boto3.client("bedrock-runtime", region_name=region)
        self.client = client

    def review(self, request: ReviewRequest) -> Review:
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": request.system}],
            messages=[{"role": "user", "content": [{"text": request.prompt}]}],
            toolConfig=tool_spec_bedrock(),
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0},
        )
        return parse_converse_response(response)


class AnthropicProvider:
    name = "anthropic"
    is_ai = True

    def __init__(self, model_id: str | None = None, client: Any = None, max_tokens: int = 2000):
        self.model_id = model_id or DEFAULT_ANTHROPIC_MODEL
        self.max_tokens = max_tokens
        if client is None:
            try:
                import anthropic  # optional dependency
            except ImportError as exc:
                raise RuntimeError(
                    "anthropic provider needs: pip install changeset-sentinel[anthropic]"
                ) from exc
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.client = client

    def review(self, request: ReviewRequest) -> Review:
        message = self.client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=0,
            system=request.system,
            messages=[{"role": "user", "content": request.prompt}],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Submit the structured change set review.",
                    "input_schema": REVIEW_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )
        return parse_anthropic_message(message)


class RuleBasedProvider:
    """Deterministic narrative. Used for the offline demo, tests, and AI fallback."""

    is_ai = False
    model_id = None

    def __init__(self, name: str = "mock") -> None:
        self.name = name

    def review(self, request: ReviewRequest) -> Review:
        from sentinel.narrative import rule_based_review  # local import avoids a cycle

        return rule_based_review(request.assessment, request.stack_name, request.physical_ids)


def get_provider(name: str, model_id: str | None = None, region: str | None = None) -> Provider:
    key = (name or "none").strip().lower()
    if key == "bedrock":
        return BedrockProvider(model_id=model_id or None, region=region)
    if key == "anthropic":
        # A Bedrock style ID (us.anthropic.x or anthropic.x) means the caller kept the
        # workflow default, so fall back to the Anthropic API model name.
        if model_id and "anthropic." in model_id:
            model_id = None
        return AnthropicProvider(model_id=model_id or None)
    if key in {"mock", "none"}:
        return RuleBasedProvider(name=key)
    raise ValueError(f"unknown provider: {name} (use bedrock, anthropic, mock or none)")
