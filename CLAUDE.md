# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this repo is

changeset-sentinel reviews CloudFormation change sets on pull requests. A deterministic
rules engine scores the change, Claude on Amazon Bedrock writes the risk narrative and
rollback plan, and a merge gate blocks high risk changes until a human applies the
`risk-accepted` label.

## Layout

- `sentinel/` Python package: `changeset.py` parser, `risk.py` rules engine, `redact.py`,
  `prompt.py`, `llm.py` providers, `narrative.py` rule-based text, `review.py` orchestration,
  `gate.py`, `report.py`, `github.py`, `allowlist.py`, `cli.py`
- `actions/` composite actions: changeset, policy-scan, ai-review, allowlist
- `.github/workflows/sentinel-review.yml` reusable workflow callers pin at `@v1`
- `bootstrap/github-oidc.yaml` OIDC provider and review-only role
- `policy/` cfn-guard rules and the actions allowlist
- `examples/` demo stack plus recorded change set scenarios
- `templates/new-service/` scaffold copied by `scripts/new-service.sh`

## Commands

```bash
make install     # package plus dev tools
make lint        # ruff check and format check
make test        # pytest, fully offline
make iac         # cfn-lint all templates
make guard       # cfn-guard policy rules
make demo        # offline demo over recorded change sets
make allowlist   # dogfood the actions allowlist
```

## Conventions

- Python 3.12, ruff with line length 100, type hints everywhere.
- New risk rules go in `sentinel/risk.py` RULES and `docs/RISK_RULES.md` together, with a test.
- New scenarios need `template.yaml`, `changeset.json` (real describe-change-set shape) and a test.
- Writing style for docs, comments and commit messages: no em dash characters and no quotation marks in prose.

## Guardrails

- Never add a code path that executes a change set or mutates a stack.
- Never let model output lower the deterministic floor (`review.apply_floor`).
- Anything sent to a model must go through `prompt.build_payload` so redaction applies.
- Never commit credentials or secrets. VPC and subnet IDs in demo parameter files are fine.
- Pin every new GitHub Action and add it to `policy/actions-allowlist.yml`.
- Pass workflow inputs to shell steps through `env:`, never inline expressions.
