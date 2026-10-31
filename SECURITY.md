# Security

## Design guarantees

- **Review only.** The IAM role in `bootstrap/github-oidc.yaml` can create, describe and delete change sets. An explicit Deny blocks ExecuteChangeSet, CreateStack, UpdateStack and DeleteStack.
- **No static credentials.** GitHub Actions authenticates to AWS with OIDC. The trust policy only accepts `pull_request` tokens from one repository, and fork pull requests never receive an OIDC token.
- **Secrets never reach the model.** Change set values are redacted (key names such as Password or Token, plus known credential formats) before the prompt is built. The count is printed in every report.
- **The AI cannot weaken the gate.** The deterministic rules set a floor. The model can raise risk, never lower it, and a model outage falls back to the rule-based report.
- **Supply chain.** Every `uses:` reference is checked against `policy/actions-allowlist.yml` and must be pinned. Workflow inputs reach shell steps through environment variables, never inline expressions.

## Reporting a vulnerability

Please open a private security advisory on this repository (Security tab, Report a vulnerability) rather than a public issue. I aim to respond within five business days.
