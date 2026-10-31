from pathlib import Path

import pytest

from sentinel.allowlist import Policy, check_reference, scan
from tests.conftest import ROOT

POLICY = Policy(
    allowed=(
        "actions/*",
        "aws-actions/configure-aws-credentials",
        "TyroneMadison/changeset-sentinel",
    )
)


@pytest.mark.parametrize(
    "uses",
    [
        "actions/checkout@v5",
        "actions/setup-python@v6.0.0",
        "aws-actions/configure-aws-credentials@v4",
        "actions/checkout@" + "a" * 40,
        "TyroneMadison/changeset-sentinel/actions/ai-review@v1",
        "TyroneMadison/changeset-sentinel/.github/workflows/sentinel-review.yml@v1",
        "./actions/local",
    ],
)
def test_allowed_references(uses):
    assert check_reference(uses, POLICY) is None


@pytest.mark.parametrize(
    ("uses", "problem"),
    [
        ("actions/checkout", "not pinned"),
        ("actions/checkout@main", "branch"),
        ("evil/exfiltrate@v1", "not on the approved list"),
        ("aws-actions/configure-aws-credentials-fork@v4", "not on the approved list"),
        ("docker://alpine:3.20", "docker"),
    ],
)
def test_rejected_references(uses, problem):
    assert problem in check_reference(uses, POLICY)


def test_sha_only_mode_rejects_tags():
    strict = Policy(allowed=("actions/*",), pinning="sha")
    assert "40 character" in check_reference("actions/checkout@v5", strict)
    assert check_reference("actions/checkout@" + "b" * 40, strict) is None


def test_local_actions_can_be_disallowed():
    assert check_reference("./x", Policy(allowed=(), allow_local=False))


def test_scan_finds_violations(tmp_path: Path):
    wf = tmp_path / "wf.yml"
    wf.write_text(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v5\n      - uses: random/action@main\n"
    )
    report = scan([str(tmp_path)], POLICY)
    assert report.checked == 2
    assert [v.uses for v in report.violations] == ["random/action@main"]


def test_scan_ignores_non_workflow_yaml(tmp_path: Path):
    (tmp_path / "config.yml").write_text("uses: not/a-workflow@main\n")
    assert scan([str(tmp_path)], POLICY).checked == 0


def test_this_repo_passes_its_own_policy():
    policy = Policy.load(ROOT / "policy" / "actions-allowlist.yml")
    report = scan(
        [str(ROOT / ".github" / "workflows"), str(ROOT / "actions"), str(ROOT / "templates")],
        policy,
    )
    assert report.ok, report.violations
    assert report.checked > 5
