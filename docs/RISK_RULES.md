# Risk rules

The deterministic engine in `sentinel/risk.py` scores every resource change. The highest
finding becomes the **floor**. The AI review can raise the final level, never lower it.

## Levels

| Level | Meaning | Default gate (threshold HIGH) |
|---|---|---|
| 🟢 LOW | Additive or metadata only | Pass |
| 🟡 MEDIUM | Needs a reviewer who knows the service | Pass |
| 🟠 HIGH | Security posture or access changes | Blocked until `risk-accepted` |
| 🔴 CRITICAL | Data can be lost or a stateful resource rebuilt | Blocked until `risk-accepted` |

## Rule catalog

| Rule | Level | Fires when |
|---|---|---|
| SENT001 | CRITICAL | A stateful resource has `Replacement` True or Conditional |
| SENT002 | CRITICAL | A stateful resource is removed |
| SENT003 | HIGH | An access control resource is modified or removed, or any policy grants Action * on Resource * |
| SENT004 | HIGH | Security group ingress changes, or any rule opens a port to 0.0.0.0/0 or ::/0 |
| SENT005 | HIGH | A new or modified resource carries a secret-looking value in plain text |
| SENT006 | MEDIUM | A stateless resource is replaced |
| SENT007 | MEDIUM | A stateless resource is removed |
| SENT008 | MEDIUM | A stateful resource is updated in place |
| SENT009 | MEDIUM | A nested stack changes (its own change set holds the detail) |
| SENT013 | MEDIUM | Import or dynamic actions that need a manual look |
| SENT014 | MEDIUM | A new role or policy without wildcards |
| SENT015 | MEDIUM | A new security group with ingress from private ranges only |
| SENT010 | LOW | Only tags change |
| SENT011 | LOW | A new resource that is not access control or network |
| SENT012 | LOW | A stateless in-place update |

## Stateful types

RDS instances and clusters, DynamoDB tables, S3 buckets, OpenSearch and Elasticsearch
domains, EFS and FSx file systems, CloudWatch log groups, ElastiCache replication groups,
DocumentDB and Neptune clusters, Kinesis streams, KMS keys and Secrets Manager secrets.

## Why new roles are MEDIUM, not HIGH

A brand new service stack always adds roles and security groups. Blocking every new
stack trains people to click through the gate. New access control without wildcards is
MEDIUM and still shows in the report. Changes to existing access, wildcard grants and
anything open to the internet are HIGH.

## Adding a rule

1. Add the ID, title and level to `RULES` in `sentinel/risk.py`.
2. Add the detection in `_assess_resource`.
3. Add a narrative line in `sentinel/narrative.py` if the rule needs a rollback or check.
4. Add a row to this table and a test in `tests/test_risk.py`.
