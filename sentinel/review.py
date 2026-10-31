"""Orchestrates one review: rules, redaction, model call, floor rule, fallback."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel.changeset import ChangeSet
from sentinel.llm import Provider, Review, ReviewRequest, RuleBasedProvider
from sentinel.prompt import SYSTEM_PROMPT, build_prompt
from sentinel.risk import Assessment, RiskLevel, assess


@dataclass(frozen=True)
class ReviewResult:
    changeset: ChangeSet
    assessment: Assessment
    review: Review
    final_level: RiskLevel
    provider: str
    model_id: str | None
    ai_used: bool
    ai_level: RiskLevel | None
    redactions: int
    ai_error: str | None = None

    @property
    def floor_kept(self) -> bool:
        """True when the model suggested a lower level and the floor overruled it."""
        return self.ai_level is not None and self.ai_level < self.assessment.floor


def apply_floor(floor: RiskLevel, ai_level: RiskLevel | None) -> RiskLevel:
    """The core safety rule: AI can raise risk, never lower it."""
    return floor if ai_level is None else max(floor, ai_level)


def run_review(changeset: ChangeSet, provider: Provider) -> ReviewResult:
    assessment = assess(changeset)
    prompt, redactions = build_prompt(changeset, assessment)
    physical_ids = {rc.logical_id: rc.physical_id for rc in changeset.changes if rc.physical_id}
    request = ReviewRequest(
        system=SYSTEM_PROMPT,
        prompt=prompt,
        assessment=assessment,
        stack_name=changeset.stack_name,
        physical_ids=physical_ids,
    )

    ai_error = None
    used = provider
    try:
        review = provider.review(request)
    except Exception as exc:  # any provider failure falls back, the gate must still run
        ai_error = f"{type(exc).__name__}: {str(exc)[:200]}"
        used = RuleBasedProvider(name="fallback")
        review = used.review(request)

    ai_level = review.risk_level if used.is_ai else None
    return ReviewResult(
        changeset=changeset,
        assessment=assessment,
        review=review,
        final_level=apply_floor(assessment.floor, ai_level),
        provider=used.name,
        model_id=used.model_id,
        ai_used=used.is_ai,
        ai_level=ai_level,
        redactions=redactions,
        ai_error=ai_error,
    )
