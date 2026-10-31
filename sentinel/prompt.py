"""Build the model prompt from a redacted view of the change set."""

from __future__ import annotations

import json
from typing import Any

from sentinel.changeset import ChangeSet, ResourceChange
from sentinel.redact import Redactor
from sentinel.risk import Assessment

MAX_CONTEXT_CHARS = 6000
MAX_PROMPT_CHARS = 60000

SYSTEM_PROMPT = """You are a senior AWS platform engineer reviewing a CloudFormation change set \
before it runs in a regulated production environment.

Rules:
1. You advise. You never approve a change and you never execute anything.
2. A deterministic rules engine already scored this change. Its level is the minimum. You may \
raise the risk level if you see something it missed. Never lower it.
3. Be concrete: name logical resource IDs, the exact property changes, and AWS CLI commands \
where they help an on-call engineer.
4. Be honest about data: CloudFormation rollback restores infrastructure, not data.
5. Values shown as [REDACTED] are sensitive. Do not guess them.
6. Respond only by calling the submit_review tool."""


def _truncate(value: Any, limit: int = MAX_CONTEXT_CHARS) -> Any:
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) <= limit:
        return value
    return text[:limit] + " ...[truncated]"


def _resource_view(rc: ResourceChange, redactor: Redactor) -> dict[str, Any]:
    details = []
    for d in rc.details:
        before, after = d.before, d.after
        name = d.name or d.attribute
        before = redactor.value(name, before, rc.logical_id) if before is not None else None
        after = redactor.value(name, after, rc.logical_id) if after is not None else None
        details.append(
            {
                "attribute": d.attribute,
                "property": d.name,
                "requires_recreation": d.requires_recreation,
                "change_source": d.change_source,
                "before": before,
                "after": after,
            }
        )
    view: dict[str, Any] = {
        "logical_id": rc.logical_id,
        "type": rc.resource_type,
        "action": rc.action,
        "replacement": rc.replacement,
        "policy_action": rc.policy_action,
        "scope": list(rc.scope),
        "details": details,
    }
    if rc.before_context is not None:
        view["before"] = _truncate(redactor.walk(rc.before_properties(), f"{rc.logical_id}.before"))
    if rc.after_context is not None:
        view["after"] = _truncate(redactor.walk(rc.after_properties(), f"{rc.logical_id}.after"))
    return view


def build_payload(changeset: ChangeSet) -> tuple[dict[str, Any], int]:
    """Redacted, model friendly view of the change set and the redaction count."""
    redactor = Redactor()
    payload = {
        "stack": changeset.stack_name,
        "change_set": changeset.change_set_name,
        "parameters": {
            k: redactor.value(k, v, "Parameters") for k, v in changeset.parameters.items()
        },
        "changes": [_resource_view(rc, redactor) for rc in changeset.changes],
    }
    return payload, redactor.count


def build_prompt(changeset: ChangeSet, assessment: Assessment) -> tuple[str, int]:
    payload, redactions = build_payload(changeset)
    findings = (
        "\n".join(
            f"- [{f.level.name}] {f.rule} {f.title}: {f.logical_id} ({f.resource_type}, "
            f"{f.action}, replacement={f.replacement}). {f.reason}"
            for f in assessment.findings
        )
        or "- none"
    )
    body = json.dumps(payload, indent=1, sort_keys=True, default=str)
    if len(body) > MAX_PROMPT_CHARS:
        body = body[:MAX_PROMPT_CHARS] + "\n...[truncated, review the full change set in the run]"
    prompt = (
        f"Stack: {changeset.stack_name}\n"
        f"Change set: {changeset.change_set_name}\n"
        f"Deterministic risk floor: {assessment.floor.name}\n\n"
        f"Deterministic findings:\n{findings}\n\n"
        f"Change set, secrets redacted:\n{body}\n\n"
        "Write the review. Rollback steps must be ordered and runnable."
    )
    return prompt, redactions
