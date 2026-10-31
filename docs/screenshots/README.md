# Screenshots

Drop screenshots here after running the live demo in `docs/DEPLOY.md`. Suggested names:

| File | What to capture |
|---|---|
| `01-pr-comment-critical.png` | The sticky PR comment for scenario 02 showing CRITICAL risk, findings and rollback plan |
| `02-blocked-check.png` | The failing `demo-review / sentinel` check on the PR with the Risk gate error |
| `03-label-approved.png` | The same comment after adding `risk-accepted`, showing who approved it |
| `04-policy-scan-failure.png` | Scenario 03 run: cfn-guard and Trivy failing on open SSH |
| `05-job-summary.png` | The Actions job summary with the rendered report |
| `06-oidc-role.png` | IAM console showing the review role trust policy (sub condition visible) |

Then reference them from the README, for example `![PR comment](docs/screenshots/01-pr-comment-critical.png)`.
