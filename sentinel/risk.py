"""Deterministic risk engine.

This engine sets the risk floor for every review. The AI layer may raise the
final level when it spots something the rules missed. It can never lower it.
That keeps the merge gate predictable even when the model is wrong or offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from sentinel.changeset import ChangeSet, ResourceChange
from sentinel.redact import Redactor


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def parse(cls, value: str) -> RiskLevel:
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown risk level: {value}") from exc

    @property
    def icon(self) -> str:
        return {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴"}[self.value]


STATEFUL_TYPES = frozenset(
    {
        "AWS::RDS::DBInstance",
        "AWS::RDS::DBCluster",
        "AWS::DynamoDB::Table",
        "AWS::DynamoDB::GlobalTable",
        "AWS::S3::Bucket",
        "AWS::OpenSearchService::Domain",
        "AWS::Elasticsearch::Domain",
        "AWS::EFS::FileSystem",
        "AWS::FSx::FileSystem",
        "AWS::Logs::LogGroup",
        "AWS::ElastiCache::ReplicationGroup",
        "AWS::DocDB::DBCluster",
        "AWS::Neptune::DBCluster",
        "AWS::Kinesis::Stream",
        "AWS::KMS::Key",
        "AWS::SecretsManager::Secret",
    }
)

ACCESS_CONTROL_TYPES = frozenset(
    {
        "AWS::IAM::Role",
        "AWS::IAM::Policy",
        "AWS::IAM::ManagedPolicy",
        "AWS::IAM::RolePolicy",
        "AWS::IAM::User",
        "AWS::IAM::UserPolicy",
        "AWS::IAM::Group",
        "AWS::IAM::GroupPolicy",
        "AWS::IAM::InstanceProfile",
        "AWS::IAM::OIDCProvider",
        "AWS::S3::BucketPolicy",
        "AWS::SQS::QueuePolicy",
        "AWS::SNS::TopicPolicy",
        "AWS::Lambda::Permission",
        "AWS::KMS::Key",
    }
)

NETWORK_TYPES = frozenset(
    {
        "AWS::EC2::SecurityGroup",
        "AWS::EC2::SecurityGroupIngress",
        "AWS::EC2::SecurityGroupEgress",
        "AWS::EC2::NetworkAclEntry",
    }
)

OPEN_CIDRS = frozenset({"0.0.0.0/0", "::/0"})


@dataclass(frozen=True)
class Finding:
    rule: str
    title: str
    level: RiskLevel
    logical_id: str
    resource_type: str
    action: str
    replacement: str | None
    reason: str
    policy_action: str | None = None


@dataclass(frozen=True)
class Assessment:
    findings: tuple[Finding, ...]
    floor: RiskLevel

    def by_rule(self, rule: str) -> list[Finding]:
        return [f for f in self.findings if f.rule == rule]

    @property
    def stateful_at_risk(self) -> list[Finding]:
        return [f for f in self.findings if f.rule in {"SENT001", "SENT002"}]


# Rule catalog. Documented in docs/RISK_RULES.md, keep both in sync.
RULES = {
    "SENT001": ("Stateful resource replacement", RiskLevel.CRITICAL),
    "SENT002": ("Stateful resource removal", RiskLevel.CRITICAL),
    "SENT003": ("Access control change", RiskLevel.HIGH),
    "SENT004": ("Network exposure change", RiskLevel.HIGH),
    "SENT005": ("Hardcoded secret in template", RiskLevel.HIGH),
    "SENT006": ("Stateless resource replacement", RiskLevel.MEDIUM),
    "SENT007": ("Resource removal", RiskLevel.MEDIUM),
    "SENT008": ("Stateful in-place update", RiskLevel.MEDIUM),
    "SENT009": ("Nested stack change", RiskLevel.MEDIUM),
    "SENT010": ("Tag-only change", RiskLevel.LOW),
    "SENT011": ("Resource addition", RiskLevel.LOW),
    "SENT012": ("In-place update", RiskLevel.LOW),
    "SENT013": ("Import or dynamic change", RiskLevel.MEDIUM),
    "SENT014": ("New access control resource", RiskLevel.MEDIUM),
    "SENT015": ("New network rule", RiskLevel.MEDIUM),
}


def _finding(rule: str, rc: ResourceChange, reason: str) -> Finding:
    title, level = RULES[rule]
    return Finding(
        rule=rule,
        title=title,
        level=level,
        logical_id=rc.logical_id,
        resource_type=rc.resource_type,
        action=rc.action,
        replacement=rc.replacement,
        reason=reason,
        policy_action=rc.policy_action,
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _loads_maybe(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in "{[":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def wildcard_statements(properties: dict[str, Any]) -> list[dict[str, Any]]:
    """Allow statements granting Action * on Resource * anywhere in the properties."""
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        node = _loads_maybe(node)
        if isinstance(node, dict):
            if "Statement" in node:
                for stmt in _as_list(_loads_maybe(node["Statement"])):
                    if not isinstance(stmt, dict) or stmt.get("Effect") != "Allow":
                        continue
                    actions = [str(a) for a in _as_list(stmt.get("Action"))]
                    resources = [str(r) for r in _as_list(stmt.get("Resource"))]
                    if any(a in {"*", "*:*"} for a in actions) and "*" in resources:
                        found.append(stmt)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(properties)
    return found


def open_ingress(rc: ResourceChange) -> list[str]:
    """Human readable descriptions of ingress rules open to the internet."""
    props = rc.after_properties()
    rules: list[dict[str, Any]] = []
    if rc.resource_type == "AWS::EC2::SecurityGroup":
        rules = [r for r in _as_list(props.get("SecurityGroupIngress")) if isinstance(r, dict)]
    elif rc.resource_type == "AWS::EC2::SecurityGroupIngress":
        rules = [props]
    exposed = []
    for rule in rules:
        cidr = rule.get("CidrIp") or rule.get("CidrIpv6")
        if cidr in OPEN_CIDRS:
            proto = str(rule.get("IpProtocol", "tcp"))
            ports = "all ports" if proto == "-1" else _port_range(rule)
            exposed.append(f"{proto} {ports} from {cidr}")
    return exposed


def _port_range(rule: dict[str, Any]) -> str:
    start, end = rule.get("FromPort"), rule.get("ToPort")
    if start is None:
        return "all ports"
    return f"port {start}" if str(start) == str(end) else f"ports {start}-{end}"


def _secret_hits(rc: ResourceChange) -> list[str]:
    redactor = Redactor()
    redactor.walk(rc.after_properties(), "Properties")
    return redactor.hits


def _assess_resource(rc: ResourceChange) -> list[Finding]:
    findings: list[Finding] = []
    stateful = rc.resource_type in STATEFUL_TYPES
    changed = ", ".join(rc.changed_properties) or "properties"

    # Data first: these are the changes you cannot undo with a revert.
    if rc.is_replacement and stateful:
        findings.append(
            _finding(
                "SENT001",
                rc,
                f"Replacement={rc.replacement} triggered by {changed}. CloudFormation builds a new "
                "resource and deletes the old one, so existing data does not carry over.",
            )
        )
    elif rc.action == "Remove" and stateful:
        findings.append(
            _finding("SENT002", rc, "Resource is removed from the stack together with its data.")
        )

    if rc.resource_type in ACCESS_CONTROL_TYPES and not rc.is_tag_only:
        wild = wildcard_statements(rc.after_properties())
        reason = f"{rc.action} on an access control resource ({changed})."
        if wild:
            reason += " Grants Action * on Resource *, which is administrator access."
        if rc.action in {"Modify", "Remove"} or wild:
            findings.append(_finding("SENT003", rc, reason))
        elif rc.action == "Add":
            findings.append(
                _finding("SENT014", rc, "New role or policy. Confirm it is least privilege.")
            )

    if rc.resource_type in NETWORK_TYPES and not rc.is_tag_only and rc.action != "Remove":
        exposed = open_ingress(rc)
        open_text = " Open to the internet: " + "; ".join(exposed) + "." if exposed else ""
        if rc.action == "Add" and not exposed:
            has_rules = rc.resource_type != "AWS::EC2::SecurityGroup" or bool(
                rc.after_properties().get("SecurityGroupIngress")
            )
            if has_rules:
                findings.append(_finding("SENT015", rc, "New ingress rules from private ranges."))
        else:
            touches_ingress = rc.resource_type != "AWS::EC2::SecurityGroup" or any(
                "Ingress" in (d.name or "") for d in rc.details
            )
            if touches_ingress or exposed:
                findings.append(_finding("SENT004", rc, "Ingress rules change." + open_text))

    secrets = _secret_hits(rc) if rc.action in {"Add", "Modify"} else []
    if secrets:
        findings.append(
            _finding(
                "SENT005",
                rc,
                "Secret-looking value in "
                + ", ".join(sorted(set(secrets)))
                + ". Use Secrets Manager or an SSM SecureString dynamic reference.",
            )
        )

    if findings:
        return findings

    # Lower risk categories only apply when nothing above matched.
    if rc.resource_type == "AWS::CloudFormation::Stack" and rc.action != "Add":
        findings.append(
            _finding("SENT009", rc, "Nested stack changes. Review its own change set too.")
        )
    elif rc.is_tag_only:
        findings.append(_finding("SENT010", rc, "Only tags change. No runtime impact expected."))
    elif rc.is_replacement:
        findings.append(
            _finding(
                "SENT006",
                rc,
                f"Replacement={rc.replacement} triggered by {changed}. Physical ID changes.",
            )
        )
    elif rc.action == "Remove":
        findings.append(_finding("SENT007", rc, "Resource is deleted."))
    elif rc.action == "Modify" and stateful:
        findings.append(
            _finding(
                "SENT008",
                rc,
                f"In-place update of {changed}. Some updates cause a short interruption.",
            )
        )
    elif rc.action == "Add":
        findings.append(_finding("SENT011", rc, "New resource."))
    elif rc.action == "Modify":
        findings.append(_finding("SENT012", rc, f"In-place update of {changed}."))
    else:
        findings.append(_finding("SENT013", rc, f"Action {rc.action} needs a manual look."))
    return findings


def assess(changeset: ChangeSet) -> Assessment:
    findings = tuple(f for rc in changeset.changes for f in _assess_resource(rc))
    ordered = tuple(sorted(findings, key=lambda f: (-f.level, f.rule, f.logical_id)))
    floor = max((f.level for f in ordered), default=RiskLevel.LOW)
    return Assessment(findings=ordered, floor=floor)
