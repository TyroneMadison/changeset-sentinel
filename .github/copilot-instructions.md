# GitHub Copilot instructions

This repository is changeset-sentinel: AI-assisted review of CloudFormation change sets on pull requests.

## Architecture in one paragraph

`actions/changeset` creates a change set (never executes it), `sentinel/risk.py` scores it with deterministic rules, `sentinel/redact.py` strips secrets, `sentinel/llm.py` asks Claude on Bedrock for a structured review through forced tool use, `sentinel/review.py` applies the floor rule (AI can raise risk, never lower it), and `sentinel/report.py` plus `sentinel/github.py` post one sticky PR comment. `sentinel/gate.py` blocks the merge at or above the threshold unless a human adds the `risk-accepted` label.

## When suggesting code

- Python 3.12, type hints, ruff line length 100. Standard library first; the GitHub client uses urllib on purpose.
- Tests are offline. Use the recorded fixtures in `examples/scenarios` and fake clients, never real AWS or network calls.
- Keep the risk rule catalog in `sentinel/risk.py` and `docs/RISK_RULES.md` in sync.
- In workflows and composite actions, pass inputs through `env:` and pin every action to a tag or SHA listed in `policy/actions-allowlist.yml`.
- IAM in CloudFormation is scoped to ARNs. Never suggest Action * with Resource *.
- Docs, comments and commit messages: no em dash characters and no quotation marks in prose.

## Never

- Add code that calls ExecuteChangeSet, CreateStack, UpdateStack or DeleteStack.
- Send change set data to a model without going through `prompt.build_payload`.
- Lower a risk level based on model output.
