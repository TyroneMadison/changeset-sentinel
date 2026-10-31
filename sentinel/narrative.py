"""Rule-based review narrative.

Used when no model is configured, in the offline demo, and as the fallback when
the model call fails. It only states what the rules can prove.
"""

from __future__ import annotations

from sentinel.llm import Review
from sentinel.risk import Assessment, Finding, RiskLevel

_IMPACT = {
    "SENT001": "is replaced: a new physical resource is built and the old one deleted, so anything "
    "pointing at the old endpoint or name breaks until it is updated",
    "SENT002": "is deleted together with the data it holds",
    "SENT003": "changes who or what can act in the account, for every principal using it",
    "SENT004": "changes which networks can reach the attached resources",
    "SENT005": "would store a credential in plain text in the template and stack metadata",
    "SENT006": "is recreated with a new physical ID; CloudFormation updates in-stack references",
    "SENT007": "is removed; anything outside this stack that references it will fail",
    "SENT008": "is updated in place; some property updates cause a short interruption",
    "SENT009": "is a nested stack; its own change set holds the details",
    "SENT013": "has an import or dynamic change that needs a manual look",
    "SENT014": "adds a new role or policy that needs a least privilege check",
    "SENT015": "adds new ingress rules from private ranges",
}

_SNAPSHOT_COMMANDS = {
    "AWS::RDS::DBInstance": "aws rds create-db-snapshot --db-instance-identifier {pid} "
    "--db-snapshot-identifier pre-change-{lid}",
    "AWS::RDS::DBCluster": "aws rds create-db-cluster-snapshot --db-cluster-identifier {pid} "
    "--db-cluster-snapshot-identifier pre-change-{lid}",
    "AWS::DynamoDB::Table": "aws dynamodb create-backup --table-name {pid} "
    "--backup-name pre-change-{lid}",
    "AWS::S3::Bucket": "aws s3 sync s3://{pid} s3://YOUR-BACKUP-BUCKET/{pid}/",
    "AWS::EFS::FileSystem": "aws backup start-backup-job --backup-vault-name YOUR-VAULT "
    "--resource-arn EFS-ARN --iam-role-arn BACKUP-ROLE-ARN",
    "AWS::Logs::LogGroup": "aws logs create-export-task --log-group-name {pid} "
    "--from 0 --to NOW-MS --destination YOUR-EXPORT-BUCKET",
}

_POLICY_NOTES = {
    "Snapshot": "a final snapshot is taken, but restore is manual and later writes are lost",
    "ReplaceAndSnapshot": "a final snapshot is taken, but restore is manual and writes made "
    "after the snapshot are lost",
    "Retain": "the old resource is kept but leaves stack management",
    "ReplaceAndRetain": "the old resource is kept (orphaned), data survives but is no longer "
    "managed by the stack",
    "Delete": "no snapshot is taken, data is permanently lost",
    "ReplaceAndDelete": "no snapshot is taken, data is permanently lost",
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _snapshot_step(f: Finding, physical_ids: dict[str, str]) -> str:
    template = _SNAPSHOT_COMMANDS.get(f.resource_type)
    pid = physical_ids.get(f.logical_id) or f.logical_id
    if template:
        command = template.format(pid=pid, lid=f.logical_id.lower())
        return f"Before executing, back up {f.logical_id}: `{command}`"
    return f"Before executing, take a backup of {f.logical_id} with the service native tool."


def rule_based_review(
    assessment: Assessment,
    stack_name: str,
    physical_ids: dict[str, str] | None = None,
) -> Review:
    physical_ids = physical_ids or {}
    findings = list(assessment.findings)
    if not findings:
        return Review(
            risk_level=RiskLevel.LOW,
            summary=f"The change set for {stack_name} contains no resource changes.",
            blast_radius=["None. Nothing will change."],
            data_loss_risks=["None."],
            rollback_plan=["Nothing to roll back."],
            pre_deploy_checks=["Confirm the template change you expected is in this PR."],
            post_deploy_verification=["None required."],
        )

    top = findings[0]
    noteworthy = [f for f in findings if f.level >= RiskLevel.MEDIUM]
    summary = (
        f"{len(findings)} finding(s) on stack {stack_name}. Highest risk is {top.level.name}: "
        f"{top.title.lower()} on {top.logical_id} ({top.resource_type}). {top.reason}"
    )

    blast = [
        f"{f.logical_id} ({f.resource_type}) {_IMPACT[f.rule]}."
        for f in noteworthy
        if f.rule in _IMPACT
    ] or ["Low impact: the changes are additive or metadata only."]

    data_loss: list[str] = []
    for f in assessment.stateful_at_risk:
        note = _POLICY_NOTES.get(
            f.policy_action or "", "check DeletionPolicy and UpdateReplacePolicy"
        )
        data_loss.append(f"{f.logical_id}: data does not carry over to the new resource; {note}.")
    if not data_loss:
        data_loss = ["None identified by the deterministic rules."]

    rollback = [
        "Revert the PR commit and let the pipeline build a fresh change set from the previous "
        "template. Do not hand edit resources in the console."
    ]
    pre = [
        "Confirm the change set was created from the commit you intend to merge.",
        "Run drift detection first: `aws cloudformation detect-stack-drift "
        f"--stack-name {stack_name}`.",
    ]
    post = [f"Stack {stack_name} reaches UPDATE_COMPLETE with no drift."]

    for f in findings:
        if f.rule in {"SENT001", "SENT002"}:
            rollback.append(_snapshot_step(f, physical_ids))
            rollback.append(
                "CloudFormation rollback restores infrastructure, not data. Recovery means "
                f"restoring {f.logical_id} from that backup and pointing the stack at it."
            )
            pre.append(f"Confirm a recent restore test exists for {f.logical_id}.")
            pre.append(f"Book a maintenance window: clients of {f.logical_id} see downtime.")
            post.append(
                f"{f.logical_id} is reachable and record counts match the pre-change baseline."
            )
        elif f.rule == "SENT003":
            rollback.append(
                f"If access breaks or widens, redeploy the previous template. IAM changes to "
                f"{f.logical_id} revert within seconds."
            )
            pre.append(f"Diff the policy on {f.logical_id}: no Action * with Resource *.")
            post.append("Check CloudTrail for AccessDenied spikes after the deploy.")
        elif f.rule == "SENT004":
            rollback.append(
                f"Revert the ingress change on {f.logical_id} first, then review VPC Flow Logs "
                "and CloudTrail for traffic during the exposure window."
            )
            pre.append("Admin ports 22 and 3389 must never be open to 0.0.0.0/0 or ::/0.")
            post.append(f"An external port scan shows only intended ports open on {f.logical_id}.")
        elif f.rule == "SENT005":
            rollback.append(
                "Treat the exposed value as compromised: rotate it, then move it to "
                "Secrets Manager."
            )
            pre.append(
                "Remove the hardcoded value and use a {{resolve:secretsmanager:...}} reference."
            )
        elif f.rule == "SENT006":
            rollback.append(f"Rolling back {f.logical_id} triggers another replacement cycle.")

    post.append("Service CloudWatch alarms stay green for 30 minutes after the deploy.")
    return Review(
        risk_level=assessment.floor,
        summary=summary,
        blast_radius=_dedupe(blast),
        data_loss_risks=_dedupe(data_loss),
        rollback_plan=_dedupe(rollback),
        pre_deploy_checks=_dedupe(pre),
        post_deploy_verification=_dedupe(post),
    )
