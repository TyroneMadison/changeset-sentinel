"""Render the review as GitHub flavored markdown for the sticky PR comment."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sentinel import MARKER, __version__
from sentinel.gate import GateDecision
from sentinel.review import ReviewResult

_OUTCOME_ICON = {"success": "✅", "failure": "❌", "cancelled": "⚪", "skipped": "⚪"}


@dataclass(frozen=True)
class Check:
    name: str
    outcome: str

    @property
    def passed(self) -> bool:
        return self.outcome == "success"


@dataclass(frozen=True)
class ReportContext:
    checks: list[Check] = field(default_factory=list)
    run_url: str | None = None
    generated_at: datetime | None = None


def parse_checks(lines: list[str]) -> list[Check]:
    checks = []
    for raw in lines:
        line = raw.strip()
        if not line or "=" not in line:
            continue
        name, outcome = line.rsplit("=", 1)
        checks.append(Check(name.strip(), outcome.strip().lower() or "skipped"))
    return checks


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- None."


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{n}. {i}" for n, i in enumerate(items, 1)) or "1. None."


def _checkboxes(items: list[str]) -> str:
    return "\n".join(f"- [ ] {i}" for i in items) or "- [ ] None."


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _ai_row(result: ReviewResult) -> str:
    if result.ai_error:
        return f"Unavailable ({_cell(result.ai_error)}). Rule-based narrative used."
    if not result.ai_used:
        if result.provider == "mock":
            return "Mock provider (offline demo). Narrative is rule-based."
        return "Not requested. Narrative is rule-based."
    level = result.ai_level.name if result.ai_level else "n/a"
    if result.floor_kept:
        return f"{level}, below the floor, so the floor {result.assessment.floor.name} was kept"
    return f"{level} from `{result.model_id}`"


def _gate_row(gate: GateDecision) -> str:
    if gate.blocked:
        return f"❌ Blocked. {gate.reason}"
    if gate.approved_by_label:
        return f"✅ Approved. {gate.reason}"
    return f"✅ Pass. {gate.reason}"


def render_report(result: ReviewResult, gate: GateDecision, context: ReportContext) -> str:
    cs, review, final = result.changeset, result.review, result.final_level
    counts = cs.action_counts
    count_text = ", ".join(f"{n} {a.lower()}" for a, n in sorted(counts.items())) or "none"
    when = (context.generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        MARKER,
        f"## 🛡️ Changeset Sentinel: {final.icon} {final.name} risk",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Stack | `{cs.stack_name}` |",
        f"| Change set | `{cs.change_set_name}` |",
        f"| Resource changes | {len(cs.changes)} ({count_text}) |",
        f"| Deterministic floor | {result.assessment.floor.icon} {result.assessment.floor.name} |",
        f"| AI assessment | {_ai_row(result)} |",
        f"| Final risk | {final.icon} **{final.name}** |",
        f"| Merge gate | {_gate_row(gate)} |",
    ]

    if context.checks:
        lines += ["", "### Checks", "", "| Check | Result |", "|---|---|"]
        lines += [
            f"| {_cell(c.name)} | {_OUTCOME_ICON.get(c.outcome, '⚪')} {c.outcome} |"
            for c in context.checks
        ]
        if any(not c.passed for c in context.checks):
            lines += ["", "> A failed check blocks the merge on its own. See the job log."]

    lines += ["", "### Summary", "", review.summary, "", "### Findings", ""]
    if result.assessment.findings:
        lines += [
            "| Level | Rule | Resource | Type | Action | Replacement | Why |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {f.level.icon} {f.level.name} | {f.rule} | `{f.logical_id}` | {f.resource_type} "
            f"| {f.action} | {f.replacement or 'n/a'} | {_cell(f.reason)} |"
            for f in result.assessment.findings
        ]
    else:
        lines.append("No resource changes.")

    lines += [
        "",
        "### Blast radius",
        "",
        _bullets(review.blast_radius),
        "",
        "### Data loss risks",
        "",
        _bullets(review.data_loss_risks),
        "",
        "### Rollback plan",
        "",
        _numbered(review.rollback_plan),
        "",
        "### Pre-deploy checks",
        "",
        _checkboxes(review.pre_deploy_checks),
        "",
        "### Post-deploy verification",
        "",
        _checkboxes(review.post_deploy_verification),
        "",
        "<details><summary>How this was decided</summary>",
        "",
        "- The deterministic rules engine sets the minimum risk. "
        "The AI can raise it, never lower it.",
        f"- Values redacted before the AI saw the change set: {result.redactions}.",
        f"- Provider: `{result.provider}`"
        + (f", model `{result.model_id}`" if result.model_id else "")
        + ".",
        "- The change set was created for review only and deleted afterwards. "
        "Nothing was executed.",
    ]
    if gate.approved_by_label:
        lines.append(f"- Approval evidence: {gate.reason}")
    if context.run_url:
        lines.append(f"- Workflow run: {context.run_url}")
    lines += [
        f"- Generated {when} by changeset-sentinel v{__version__}.",
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)
