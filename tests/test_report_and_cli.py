import json
from datetime import UTC, datetime

from sentinel import MARKER
from sentinel.cli import main
from sentinel.gate import decide
from sentinel.llm import RuleBasedProvider
from sentinel.report import Check, ReportContext, parse_checks, render_report
from sentinel.review import run_review
from tests.conftest import SCENARIOS, scenario

FIXED = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def render(name, labels=(), checks=None):
    result = run_review(scenario(name), RuleBasedProvider("mock"))
    gate = decide(result.final_level, "HIGH", labels)
    return render_report(result, gate, ReportContext(checks=checks or [], generated_at=FIXED))


def test_report_has_marker_and_sections():
    md = render("02-rds-engine-change")
    assert md.startswith(MARKER)
    assert "CRITICAL risk" in md
    for section in (
        "### Findings",
        "### Blast radius",
        "### Data loss risks",
        "### Rollback plan",
        "### Pre-deploy checks",
        "### Post-deploy verification",
    ):
        assert section in md
    assert "aws rds create-db-snapshot" in md
    assert "❌ Blocked" in md


def test_report_shows_label_approval():
    md = render("02-rds-engine-change", labels=["risk-accepted"])
    assert "✅ Approved" in md
    assert "Approval evidence" in md


def test_report_lists_failed_checks():
    md = render("01-tag-change", checks=[Check("Policy scan", "failure")])
    assert "| Policy scan | ❌ failure |" in md
    assert "A failed check blocks the merge" in md


def test_report_follows_writing_rules():
    for name in (
        "01-tag-change",
        "02-rds-engine-change",
        "03-open-ssh-security-group",
        "04-iam-wildcard",
    ):
        md = render(name)
        assert "\u2014" not in md
        assert "\u201c" not in md
        assert "\u201d" not in md


def test_parse_checks():
    checks = parse_checks(["Actions allowlist=success", "", "Policy scan = failure", "junk"])
    assert checks == [Check("Actions allowlist", "success"), Check("Policy scan", "failure")]


def test_cli_review_blocks_critical(tmp_path, capsys):
    out = tmp_path / "report.md"
    code = main(
        [
            "review",
            "--changeset",
            str(SCENARIOS / "02-rds-engine-change" / "changeset.json"),
            "--provider",
            "mock",
            "--output",
            str(out),
        ]
    )
    assert code == 1
    assert "CRITICAL" in out.read_text()


def test_cli_review_label_unblocks(tmp_path, monkeypatch):
    output = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    code = main(
        [
            "review",
            "--changeset",
            str(SCENARIOS / "03-open-ssh-security-group" / "changeset.json"),
            "--label",
            "risk-accepted",
            "--output",
            str(tmp_path / "r.md"),
        ]
    )
    assert code == 0
    assert "risk-level=HIGH" in output.read_text()
    assert "blocked=false" in output.read_text()


def test_cli_review_passes_low(tmp_path):
    code = main(
        [
            "review",
            "--changeset",
            str(SCENARIOS / "01-tag-change" / "changeset.json"),
            "--output",
            str(tmp_path / "r.md"),
        ]
    )
    assert code == 0


def test_cli_bad_changeset_is_usage_error(tmp_path):
    bad = tmp_path / "cs.json"
    bad.write_text(json.dumps({"Status": "FAILED", "StatusReason": "Template format error"}))
    assert main(["review", "--changeset", str(bad)]) == 2


def test_cli_demo_writes_reports(tmp_path, capsys):
    assert main(["demo", "--scenarios", str(SCENARIOS), "--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.md"))) == 4
    table = capsys.readouterr().out
    assert "02-rds-engine-change" in table
    assert "blocked" in table


def test_cli_allowlist_on_repo():
    root = SCENARIOS.parent.parent
    code = main(
        [
            "allowlist",
            "--policy",
            str(root / "policy" / "actions-allowlist.yml"),
            str(root / ".github" / "workflows"),
            str(root / "actions"),
        ]
    )
    assert code == 0
