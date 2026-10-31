import pytest

from sentinel.changeset import parse_changeset
from tests.conftest import changeset_of, resource_change, scenario


def test_parses_scenario_with_contexts():
    cs = scenario("02-rds-engine-change")
    assert cs.stack_name == "sentinel-demo-app"
    (rc,) = cs.changes
    assert rc.is_replacement
    assert rc.policy_action == "ReplaceAndSnapshot"
    assert rc.after_properties()["Engine"] == "postgres"
    assert rc.before_properties()["Engine"] == "mysql"
    assert rc.changed_properties == ["EnableCloudwatchLogsExports", "Engine", "EngineVersion"]


def test_tag_only_detection():
    cs = scenario("01-tag-change")
    assert all(rc.is_tag_only for rc in cs.changes)


def test_parameters_are_flattened():
    cs = scenario("01-tag-change")
    assert cs.parameters["Environment"] == "dev"


def test_no_change_failure_is_empty_changeset():
    cs = parse_changeset(
        {
            "StackName": "s",
            "ChangeSetName": "c",
            "Status": "FAILED",
            "StatusReason": "The submitted information didn't contain changes. Submit different "
            "information to create a change set.",
        }
    )
    assert cs.no_changes


def test_real_failure_raises():
    with pytest.raises(ValueError, match="Template format error"):
        parse_changeset({"Status": "FAILED", "StatusReason": "Template format error: bad"})


def test_non_resource_changes_are_ignored():
    cs = changeset_of(resource_change(), {"Type": "HookInvocation"})
    assert len(cs.changes) == 1


def test_invalid_context_is_kept_raw():
    cs = changeset_of(resource_change(AfterContext="not json"))
    assert cs.changes[0].after_context == {"_raw": "not json"}


def test_action_counts():
    cs = scenario("04-iam-wildcard")
    assert cs.action_counts == {"Modify": 1, "Add": 1}
