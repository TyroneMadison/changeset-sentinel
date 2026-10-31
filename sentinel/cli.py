"""Command line entry point.

    python -m sentinel review --changeset changeset.json --provider bedrock --github
    python -m sentinel allowlist --policy policy/actions-allowlist.yml .github/workflows
    python -m sentinel demo --scenarios examples/scenarios --out out

Exit codes: 0 pass, 1 blocked or policy violation, 2 usage or runtime error.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sentinel import allowlist
from sentinel.changeset import load_changeset
from sentinel.gate import decide
from sentinel.github import GitHubClient, append_env_file, pull_request_number, set_output
from sentinel.llm import get_provider
from sentinel.report import ReportContext, parse_checks, render_report
from sentinel.review import run_review

EXIT_OK, EXIT_BLOCKED, EXIT_ERROR = 0, 1, 2


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _run_url() -> str | None:
    server, repo, run = (
        os.environ.get("GITHUB_SERVER_URL"),
        os.environ.get("GITHUB_REPOSITORY"),
        os.environ.get("GITHUB_RUN_ID"),
    )
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else None


def cmd_review(args: argparse.Namespace) -> int:
    changeset = load_changeset(args.changeset)
    provider = get_provider(args.provider, args.model_id, args.region)

    labels = set(args.label or [])
    client, pr, approver = None, args.pr, None
    if args.github:
        token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
        pr = pr or pull_request_number()
        if token and repo and pr:
            client = GitHubClient(
                token, repo, os.environ.get("GITHUB_API_URL", "https://api.github.com")
            )
            labels |= set(client.list_labels(pr))
            if args.approval_label in labels:
                approver = client.label_actor(pr, args.approval_label)
        else:
            _log("GitHub posting skipped: needs GITHUB_TOKEN, GITHUB_REPOSITORY and a PR number.")

    result = run_review(changeset, provider)
    gate = decide(result.final_level, args.threshold, labels, args.approval_label, approver)
    check_lines = list(args.check or []) + os.environ.get("SENTINEL_CHECKS", "").splitlines()
    context = ReportContext(checks=parse_checks(check_lines), run_url=_run_url())
    markdown = render_report(result, gate, context)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if client and pr:
        action, comment_id = client.upsert_comment(pr, markdown)
        _log(f"PR #{pr}: comment {comment_id} {action}.")
    append_env_file("GITHUB_STEP_SUMMARY", markdown)
    set_output("risk-level", result.final_level.name)
    set_output("blocked", str(gate.blocked).lower())

    if result.ai_error:
        _log(f"AI review unavailable, rule-based narrative used: {result.ai_error}")
    _log(f"Final risk {result.final_level.name}. {gate.reason}")
    return EXIT_BLOCKED if gate.blocked else EXIT_OK


def cmd_allowlist(args: argparse.Namespace) -> int:
    policy = allowlist.Policy.load(args.policy)
    report = allowlist.scan(args.paths, policy)
    for v in report.violations:
        print(f"::error file={v.file}::{v.uses}: {v.problem}")
    status = "OK" if report.ok else f"{len(report.violations)} violation(s)"
    _log(f"Actions allowlist: {report.checked} reference(s) checked, {status}.")
    return EXIT_OK if report.ok else EXIT_BLOCKED


def cmd_demo(args: argparse.Namespace) -> int:
    scenarios = sorted(
        p for p in Path(args.scenarios).iterdir() if (p / "changeset.json").is_file()
    )
    if not scenarios:
        _log(f"No scenarios found under {args.scenarios}")
        return EXIT_ERROR
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    provider = get_provider(args.provider, args.model_id, args.region)

    header = f"{'Scenario':<30} {'Floor':<9} {'Final':<9} {'Gate':<8} Top finding"
    print(header)
    print("-" * len(header))
    for scenario in scenarios:
        result = run_review(load_changeset(scenario / "changeset.json"), provider)
        gate = decide(result.final_level, args.threshold, set(), "risk-accepted")
        markdown = render_report(result, gate, ReportContext())
        (out / f"{scenario.name}.md").write_text(markdown, encoding="utf-8")
        top = result.assessment.findings[0] if result.assessment.findings else None
        top_text = f"{top.rule} {top.title} on {top.logical_id}" if top else "no changes"
        print(
            f"{scenario.name:<30} {result.assessment.floor.name:<9} {result.final_level.name:<9} "
            f"{'blocked' if gate.blocked else 'pass':<8} {top_text}"
        )
    _log(f"Reports written to {out}/")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_llm_options(p: argparse.ArgumentParser, default_provider: str) -> None:
        p.add_argument(
            "--provider",
            default=os.environ.get("SENTINEL_PROVIDER", default_provider),
            choices=["bedrock", "anthropic", "mock", "none"],
        )
        p.add_argument("--model-id", default=os.environ.get("SENTINEL_MODEL_ID") or None)
        p.add_argument("--region", default=os.environ.get("AWS_REGION") or None)
        p.add_argument("--threshold", default="HIGH", help="LOW, MEDIUM, HIGH, CRITICAL or NONE")

    review = sub.add_parser("review", help="Review one change set")
    review.add_argument("--changeset", required=True, help="describe-change-set JSON file")
    add_llm_options(review, "none")
    review.add_argument("--approval-label", default="risk-accepted")
    review.add_argument("--label", action="append", help="Offline PR label, repeatable")
    review.add_argument("--github", action="store_true", help="Read labels and post PR comment")
    review.add_argument("--pr", type=int, default=None)
    review.add_argument("--check", action="append", help="name=outcome, repeatable")
    review.add_argument("--output", help="Write markdown here instead of stdout")
    review.set_defaults(func=cmd_review)

    allow = sub.add_parser("allowlist", help="Check GitHub Actions references")
    allow.add_argument("--policy", required=True)
    allow.add_argument("paths", nargs="+")
    allow.set_defaults(func=cmd_allowlist)

    demo = sub.add_parser("demo", help="Run the recorded scenarios offline")
    demo.add_argument("--scenarios", default="examples/scenarios")
    demo.add_argument("--out", default="out")
    add_llm_options(demo, "mock")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError) as exc:
        _log(f"error: {exc}")
        return EXIT_ERROR
