"""Merge gate: deterministic, auditable, and owned by a human label."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel.risk import RiskLevel

NEVER_BLOCK = "NONE"


@dataclass(frozen=True)
class GateDecision:
    blocked: bool
    approved_by_label: bool
    threshold: str
    reason: str
    approver: str | None = None


def decide(
    final_level: RiskLevel,
    threshold: str,
    labels: list[str] | set[str] | tuple[str, ...],
    approval_label: str = "risk-accepted",
    approver: str | None = None,
) -> GateDecision:
    """Block when risk >= threshold, unless a human applied the approval label."""
    normalized = threshold.strip().upper()
    if normalized == NEVER_BLOCK:
        return GateDecision(False, False, normalized, "Gate disabled (threshold NONE).")

    limit = RiskLevel.parse(normalized)
    if final_level < limit:
        return GateDecision(
            False, False, limit.name, f"Risk {final_level.name} is below threshold {limit.name}."
        )

    if approval_label in set(labels):
        who = f" by @{approver}" if approver else ""
        return GateDecision(
            blocked=False,
            approved_by_label=True,
            threshold=limit.name,
            reason=f"Risk {final_level.name} accepted{who} with label `{approval_label}`.",
            approver=approver,
        )

    return GateDecision(
        blocked=True,
        approved_by_label=False,
        threshold=limit.name,
        reason=(
            f"Risk {final_level.name} meets threshold {limit.name}. A reviewer must add the "
            f"`{approval_label}` label after reading this report."
        ),
    )
