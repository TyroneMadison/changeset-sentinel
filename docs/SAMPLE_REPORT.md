# Sample report

Rendered by the offline demo for scenario 02 (switching the database engine from MySQL to
PostgreSQL in place), with the Checks rows the reusable workflow adds from earlier steps. This
run used the mock provider, so the narrative comes from the rules engine. With `llm-provider: bedrock` the same sections are written by Claude, and the AI
assessment row shows the model ID and its level.

Everything below the line is exactly what lands in the PR comment.

---

## 🛡️ Changeset Sentinel: 🔴 CRITICAL risk

| Item | Value |
|---|---|
| Stack | `sentinel-demo-app` |
| Change set | `sentinel-1180242217-1` |
| Resource changes | 1 (1 modify) |
| Deterministic floor | 🔴 CRITICAL |
| AI assessment | Mock provider (offline demo). Narrative is rule-based. |
| Final risk | 🔴 **CRITICAL** |
| Merge gate | ❌ Blocked. Risk CRITICAL meets threshold HIGH. A reviewer must add the `risk-accepted` label after reading this report. |

### Checks

| Check | Result |
|---|---|
| Actions allowlist | ✅ success |
| Policy scan | ✅ success |

### Summary

1 finding(s) on stack sentinel-demo-app. Highest risk is CRITICAL: stateful resource replacement on AppDatabase (AWS::RDS::DBInstance). Replacement=True triggered by EnableCloudwatchLogsExports, Engine, EngineVersion. CloudFormation builds a new resource and deletes the old one, so existing data does not carry over.

### Findings

| Level | Rule | Resource | Type | Action | Replacement | Why |
|---|---|---|---|---|---|---|
| 🔴 CRITICAL | SENT001 | `AppDatabase` | AWS::RDS::DBInstance | Modify | True | Replacement=True triggered by EnableCloudwatchLogsExports, Engine, EngineVersion. CloudFormation builds a new resource and deletes the old one, so existing data does not carry over. |

### Blast radius

- AppDatabase (AWS::RDS::DBInstance) is replaced: a new physical resource is built and the old one deleted, so anything pointing at the old endpoint or name breaks until it is updated.

### Data loss risks

- AppDatabase: data does not carry over to the new resource; a final snapshot is taken, but restore is manual and writes made after the snapshot are lost.

### Rollback plan

1. Revert the PR commit and let the pipeline build a fresh change set from the previous template. Do not hand edit resources in the console.
2. Before executing, back up AppDatabase: `aws rds create-db-snapshot --db-instance-identifier sentinel-demo-app-appdatabase-kq81nzt0w7xe --db-snapshot-identifier pre-change-appdatabase`
3. CloudFormation rollback restores infrastructure, not data. Recovery means restoring AppDatabase from that backup and pointing the stack at it.

### Pre-deploy checks

- [ ] Confirm the change set was created from the commit you intend to merge.
- [ ] Run drift detection first: `aws cloudformation detect-stack-drift --stack-name sentinel-demo-app`.
- [ ] Confirm a recent restore test exists for AppDatabase.
- [ ] Book a maintenance window: clients of AppDatabase see downtime.

### Post-deploy verification

- [ ] Stack sentinel-demo-app reaches UPDATE_COMPLETE with no drift.
- [ ] AppDatabase is reachable and record counts match the pre-change baseline.
- [ ] Service CloudWatch alarms stay green for 30 minutes after the deploy.

<details><summary>How this was decided</summary>

- The deterministic rules engine sets the minimum risk. The AI can raise it, never lower it.
- Values redacted before the AI saw the change set: 0.
- Provider: `mock`.
- The change set was created for review only and deleted afterwards. Nothing was executed.
- Generated 2026-10-31 14:02 UTC by changeset-sentinel v1.0.0.

</details>
