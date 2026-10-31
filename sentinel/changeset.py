"""Parse the JSON produced by `aws cloudformation describe-change-set --include-property-values`."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NO_CHANGE_REASONS = (
    "didn't contain changes",
    "did not contain changes",
    "No updates are to be performed",
)


@dataclass(frozen=True)
class Detail:
    """One property level change inside a resource change."""

    attribute: str
    name: str | None = None
    requires_recreation: str | None = None
    change_source: str | None = None
    evaluation: str | None = None
    attribute_change_type: str | None = None
    path: str | None = None
    before: str | None = None
    after: str | None = None


@dataclass(frozen=True)
class ResourceChange:
    logical_id: str
    resource_type: str
    action: str
    physical_id: str | None = None
    replacement: str | None = None
    policy_action: str | None = None
    scope: tuple[str, ...] = ()
    details: tuple[Detail, ...] = ()
    before_context: dict[str, Any] | None = None
    after_context: dict[str, Any] | None = None

    @property
    def is_replacement(self) -> bool:
        return self.action == "Modify" and self.replacement in {"True", "Conditional"}

    @property
    def is_tag_only(self) -> bool:
        if self.action != "Modify" or self.is_replacement:
            return False
        if self.scope:
            return set(self.scope) == {"Tags"}
        return bool(self.details) and all(d.attribute == "Tags" for d in self.details)

    @property
    def changed_properties(self) -> list[str]:
        names = [d.name for d in self.details if d.name]
        return sorted(set(names))

    def after_properties(self) -> dict[str, Any]:
        return _properties(self.after_context)

    def before_properties(self) -> dict[str, Any]:
        return _properties(self.before_context)


@dataclass(frozen=True)
class ChangeSet:
    stack_name: str
    change_set_name: str
    status: str
    status_reason: str | None
    execution_status: str | None
    parameters: dict[str, str] = field(default_factory=dict)
    changes: tuple[ResourceChange, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def no_changes(self) -> bool:
        return not self.changes

    @property
    def action_counts(self) -> dict[str, int]:
        return dict(Counter(c.action for c in self.changes))


def _properties(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    props = context.get("Properties", context)
    return props if isinstance(props, dict) else {}


def _parse_context(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"_raw": value}
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    return {"_raw": value}


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _parse_detail(item: dict[str, Any]) -> Detail:
    target = item.get("Target") or {}
    return Detail(
        attribute=target.get("Attribute", "Unknown"),
        name=target.get("Name"),
        requires_recreation=target.get("RequiresRecreation"),
        change_source=item.get("ChangeSource"),
        evaluation=item.get("Evaluation"),
        attribute_change_type=target.get("AttributeChangeType"),
        path=target.get("Path"),
        before=_as_text(target.get("BeforeValue")),
        after=_as_text(target.get("AfterValue")),
    )


def _parse_resource_change(item: dict[str, Any]) -> ResourceChange | None:
    if item.get("Type") != "Resource":
        return None
    rc = item.get("ResourceChange") or {}
    return ResourceChange(
        logical_id=rc.get("LogicalResourceId", "Unknown"),
        resource_type=rc.get("ResourceType", "Unknown"),
        action=rc.get("Action", "Unknown"),
        physical_id=rc.get("PhysicalResourceId"),
        replacement=rc.get("Replacement"),
        policy_action=rc.get("PolicyAction"),
        scope=tuple(rc.get("Scope") or ()),
        details=tuple(_parse_detail(d) for d in rc.get("Details") or ()),
        before_context=_parse_context(rc.get("BeforeContext")),
        after_context=_parse_context(rc.get("AfterContext")),
    )


def parse_changeset(data: dict[str, Any]) -> ChangeSet:
    """Build a ChangeSet from describe-change-set output.

    A FAILED change set whose reason says there were no changes is treated as an
    empty change set rather than an error, matching how CloudFormation reports it.
    """
    status = data.get("Status", "UNKNOWN")
    reason = data.get("StatusReason")
    if status == "FAILED" and not any(r in (reason or "") for r in NO_CHANGE_REASONS):
        raise ValueError(f"change set failed: {reason or 'no reason given'}")

    changes = tuple(
        rc for rc in (_parse_resource_change(i) for i in data.get("Changes") or ()) if rc
    )
    parameters = {
        p.get("ParameterKey", ""): str(p.get("ParameterValue", ""))
        for p in data.get("Parameters") or ()
        if p.get("ParameterKey")
    }
    return ChangeSet(
        stack_name=data.get("StackName", "unknown-stack"),
        change_set_name=data.get("ChangeSetName", "unknown-change-set"),
        status=status,
        status_reason=reason,
        execution_status=data.get("ExecutionStatus"),
        parameters=parameters,
        changes=changes,
        raw=data,
    )


def load_changeset(path: str | Path) -> ChangeSet:
    with Path(path).open(encoding="utf-8") as handle:
        return parse_changeset(json.load(handle))
