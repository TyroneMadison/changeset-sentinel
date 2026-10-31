import json

import pytest

from sentinel.risk import RiskLevel, assess, wildcard_statements
from tests.conftest import changeset_of, resource_change, scenario


@pytest.mark.parametrize(
    ("name", "floor", "top_rule"),
    [
        ("01-tag-change", RiskLevel.LOW, "SENT010"),
        ("02-rds-engine-change", RiskLevel.CRITICAL, "SENT001"),
        ("03-open-ssh-security-group", RiskLevel.HIGH, "SENT004"),
        ("04-iam-wildcard", RiskLevel.HIGH, "SENT003"),
    ],
)
def test_scenarios(name, floor, top_rule):
    assessment = assess(scenario(name))
    assert assessment.floor == floor
    assert assessment.findings[0].rule == top_rule


def test_open_ssh_reason_names_the_port():
    finding = assess(scenario("03-open-ssh-security-group")).findings[0]
    assert "tcp port 22 from 0.0.0.0/0" in finding.reason


def test_hardcoded_secret_is_a_finding():
    rules = {f.rule for f in assess(scenario("04-iam-wildcard")).findings}
    assert rules == {"SENT003", "SENT005"}


def test_stateful_removal_is_critical():
    cs = changeset_of(
        resource_change(Action="Remove", ResourceType="AWS::DynamoDB::Table", Details=[], Scope=[])
    )
    assert assess(cs).floor == RiskLevel.CRITICAL
    assert assess(cs).findings[0].rule == "SENT002"


def test_conditional_replacement_of_stateful_is_critical():
    cs = changeset_of(
        resource_change(ResourceType="AWS::RDS::DBCluster", Replacement="Conditional")
    )
    assert assess(cs).floor == RiskLevel.CRITICAL


def test_stateless_replacement_is_medium():
    cs = changeset_of(resource_change(Replacement="True"))
    assert assess(cs).findings[0].rule == "SENT006"
    assert assess(cs).floor == RiskLevel.MEDIUM


def test_stateful_in_place_update_is_medium():
    cs = changeset_of(resource_change(ResourceType="AWS::RDS::DBInstance"))
    assert assess(cs).findings[0].rule == "SENT008"


def test_stateless_in_place_update_is_low():
    cs = changeset_of(resource_change())
    assert assess(cs).findings[0].rule == "SENT012"
    assert assess(cs).floor == RiskLevel.LOW


def test_new_role_without_wildcard_is_medium_not_high():
    cs = changeset_of(
        resource_change(Action="Add", ResourceType="AWS::IAM::Role", Details=[], Scope=[])
    )
    assert assess(cs).findings[0].rule == "SENT014"


def test_new_policy_with_wildcard_is_high():
    doc = {"Statement": [{"Effect": "Allow", "Action": ["*"], "Resource": "*"}]}
    cs = changeset_of(
        resource_change(
            Action="Add",
            ResourceType="AWS::IAM::Policy",
            Details=[],
            AfterContext=json.dumps({"Properties": {"PolicyDocument": doc}}),
        )
    )
    assert assess(cs).findings[0].rule == "SENT003"


def test_new_security_group_with_private_ingress_is_medium():
    props = {
        "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 443, "CidrIp": "10.0.0.0/8"}]
    }
    cs = changeset_of(
        resource_change(
            Action="Add",
            ResourceType="AWS::EC2::SecurityGroup",
            Details=[],
            AfterContext=json.dumps({"Properties": props}),
        )
    )
    assert assess(cs).findings[0].rule == "SENT015"


def test_all_traffic_open_is_reported():
    props = {"SecurityGroupIngress": [{"IpProtocol": "-1", "CidrIpv6": "::/0"}]}
    cs = changeset_of(
        resource_change(
            Action="Add",
            ResourceType="AWS::EC2::SecurityGroup",
            Details=[],
            AfterContext=json.dumps({"Properties": props}),
        )
    )
    finding = assess(cs).findings[0]
    assert finding.rule == "SENT004"
    assert "all ports from ::/0" in finding.reason


def test_nested_stack_change_is_medium():
    cs = changeset_of(resource_change(ResourceType="AWS::CloudFormation::Stack"))
    assert assess(cs).findings[0].rule == "SENT009"


def test_empty_changeset_is_low():
    assert assess(changeset_of()).floor == RiskLevel.LOW


def test_findings_sorted_highest_first():
    cs = changeset_of(
        resource_change(LogicalResourceId="Small"),
        resource_change(
            LogicalResourceId="Db", ResourceType="AWS::RDS::DBInstance", Replacement="True"
        ),
    )
    assert [f.logical_id for f in assess(cs).findings] == ["Db", "Small"]


def test_wildcard_statements_handles_json_strings():
    props = {
        "PolicyDocument": json.dumps(
            {"Statement": {"Effect": "Allow", "Action": "*", "Resource": "*"}}
        )
    }
    assert len(wildcard_statements(props)) == 1


def test_wildcard_ignores_deny():
    props = {"PolicyDocument": {"Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}}
    assert wildcard_statements(props) == []


def test_risk_level_parse():
    assert RiskLevel.parse(" high ") is RiskLevel.HIGH
    with pytest.raises(ValueError, match="unknown risk level"):
        RiskLevel.parse("SEVERE")
