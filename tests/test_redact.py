import json

from sentinel.changeset import ChangeSet
from sentinel.prompt import build_payload, build_prompt
from sentinel.redact import REDACTED, Redactor, is_sensitive_key, redact
from sentinel.risk import assess
from tests.conftest import scenario

# Built at runtime so no credential-shaped literal lives in the repo.
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_GITHUB_TOKEN = "ghp_" + "a1B2c3D4e5" * 4


def test_sensitive_keys():
    assert is_sensitive_key("MasterUserPassword")
    assert is_sensitive_key("PARTNER_API_TOKEN")
    assert is_sensitive_key("api-key")
    assert not is_sensitive_key("SecretArn")
    assert not is_sensitive_key("KmsKeyId")
    assert not is_sensitive_key("BucketName")


def test_key_based_redaction():
    data, count = redact({"DbPassword": "hunter2-not-real", "User": "admin"})
    assert data == {"DbPassword": REDACTED, "User": "admin"}
    assert count == 1


def test_references_and_short_values_are_kept():
    data, count = redact(
        {
            "ApiToken": "{{resolve:secretsmanager:prod/api:SecretString:token}}",
            "TokenValidity": "60",
            "ManageMasterUserPassword": True,
        }
    )
    assert count == 0
    assert data["ApiToken"].startswith("{{resolve:")


def test_pattern_based_redaction_anywhere():
    text = f"key={FAKE_AWS_KEY} token={FAKE_GITHUB_TOKEN}"
    data, count = redact({"Description": text})
    assert FAKE_AWS_KEY not in data["Description"]
    assert FAKE_GITHUB_TOKEN not in data["Description"]
    assert count == 2


def test_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
    data, count = redact({"Body": f"cert:\n{pem}\nend"})
    assert "MIIEow" not in data["Body"]
    assert count == 1


def test_connection_string_password():
    data, count = redact({"Url": "postgresql://app:s3cretpass@db.internal:5432/app"})
    assert data["Url"] == f"postgresql://app:{REDACTED}@db.internal:5432/app"
    assert count == 1


def test_nested_json_strings_are_walked():
    inner = json.dumps({"Variables": {"SLACK_TOKEN": "abcdefghijklmnop"}})
    data, count = redact({"Environment": inner})
    assert json.loads(data["Environment"])["Variables"]["SLACK_TOKEN"] == REDACTED
    assert count == 1


def test_redactor_records_locations():
    r = Redactor()
    r.walk({"Environment": {"Variables": {"PARTNER_API_TOKEN": "pk_demo_123456"}}}, "Properties")
    assert r.hits == ["Properties.Environment.Variables.PARTNER_API_TOKEN (sensitive key)"]


def test_prompt_never_contains_the_secret():
    cs: ChangeSet = scenario("04-iam-wildcard")
    prompt, count = build_prompt(cs, assess(cs))
    assert "pk_demo_9f8e7d6c5b4a3210" not in prompt
    assert REDACTED in prompt
    assert count == 1


def test_parameters_are_redacted_in_payload():
    cs = scenario("01-tag-change")
    params = dict(cs.parameters, LegacyAccessKey=FAKE_AWS_KEY)
    payload, count = build_payload(
        ChangeSet(cs.stack_name, cs.change_set_name, cs.status, None, None, params, cs.changes)
    )
    assert payload["parameters"]["LegacyAccessKey"] == REDACTED
    assert count == 1
