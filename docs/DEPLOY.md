# Deploy and run the live demo

This guide takes you from zero to a real pull request that gets a Claude risk report and a
blocked merge check. Every command is a single line so it works in PowerShell, bash and zsh.
Region is `us-east-2` throughout.

Time: about 45 minutes, most of it waiting for RDS. Cost: well under 1 USD if you tear down the
same day (see Step 10).

---

## Step 0. Prerequisites

You need the AWS CLI v2 signed in to an account where you can create IAM roles, the GitHub CLI
(`gh`) signed in, and this repository pushed to your GitHub account.

```bash
aws sts get-caller-identity
gh auth status
```

**Success looks like:** your 12 digit account ID from the first command, and `Logged in to github.com` from the second.

---

## Step 1. Enable Claude in Amazon Bedrock

Open the Bedrock console in `us-east-2`, go to **Model access**, and request access to
**Anthropic Claude Sonnet 4.5**. First time Anthropic users fill a short use case form. Then
confirm the inference profile ID this repo defaults to:

```bash
aws bedrock list-inference-profiles --region us-east-2 --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude-sonnet-4-5')].inferenceProfileId" --output text
```

**Success looks like:** `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. If your console shows a
different or newer ID, pass it as `BedrockInferenceProfileId` and `BedrockFoundationModelId` in
Step 3 and as `model-id` in the workflow.

---

## Step 2. Publish the v1 tag

The reusable workflow references its composite actions at `@v1`, so the tag must exist on GitHub.

```bash
git push origin main --tags
```

**Success looks like:** `* [new tag] v1 -> v1` in the output, and the tag visible under Releases and tags on GitHub.

---

## Step 3. Deploy the OIDC provider and the review-only role

```bash
aws cloudformation deploy --region us-east-2 --stack-name changeset-sentinel-oidc --template-file bootstrap/github-oidc.yaml --capabilities CAPABILITY_IAM --parameter-overrides GitHubOrg=TyroneMadison GitHubRepo=changeset-sentinel StackNamePrefix=sentinel-
```

**Success looks like:** `Successfully created/updated stack - changeset-sentinel-oidc`.

If it fails with `EntityAlreadyExists` your account already trusts GitHub. Find the ARN and rerun
Step 3 with it:

```bash
aws iam list-open-id-connect-providers --output text
```

Then add `ExistingOidcProviderArn=arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com` to the `--parameter-overrides` list.

---

## Step 4. Point the repo at the role

```bash
aws cloudformation describe-stacks --region us-east-2 --stack-name changeset-sentinel-oidc --query "Stacks[0].Outputs[?OutputKey=='RoleArn'].OutputValue" --output text
```

Copy the ARN, then store it as a repository variable (not a secret, it is not sensitive):

```bash
gh variable set SENTINEL_ROLE_ARN --body "PASTE_ROLE_ARN_HERE"
gh label create risk-accepted --color B60205 --description "Reviewed and accepted a high risk infrastructure change"
```

**Success looks like:** an ARN like `arn:aws:iam::123456789012:role/changeset-sentinel-oidc-SentinelReviewRole-AbC123`,
then `Set Actions variable SENTINEL_ROLE_ARN` and `Label risk-accepted created`.

---

## Step 5. Create the demo stack

Find your default VPC and two of its subnets:

```bash
aws ec2 describe-vpcs --region us-east-2 --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text
aws ec2 describe-subnets --region us-east-2 --filters Name=default-for-az,Values=true --query "Subnets[0:2].SubnetId" --output text
```

Put those IDs into `examples/demo-stack/parameters.json` (replace the `REPLACE` values; the
subnet value is the two IDs joined by a comma, no space). Then create the stack:

```bash
aws cloudformation create-stack --region us-east-2 --stack-name sentinel-demo-app --template-body file://examples/demo-stack/template.yaml --capabilities CAPABILITY_IAM --parameters file://examples/demo-stack/parameters.json
aws cloudformation wait stack-create-complete --region us-east-2 --stack-name sentinel-demo-app
```

**Success looks like:** the first command prints a `StackId`; the wait returns with no output after
about 10 minutes (RDS is the slow part). Commit the edited parameters file:

```bash
git add examples/demo-stack/parameters.json
git commit -m "chore: demo stack parameters for my account"
git push
```

VPC and subnet IDs are not secrets.

---

## Step 6. Open a CRITICAL pull request (scenario 02)

Replay the engine change from MySQL to PostgreSQL:

```bash
git checkout -b demo/rds-engine-change
cp examples/scenarios/02-rds-engine-change/template.yaml examples/demo-stack/template.yaml
git commit -am "demo: switch database engine to postgres"
git push -u origin demo/rds-engine-change
gh pr create --fill
```

In PowerShell use `Copy-Item` instead of `cp`.

**Success looks like:** within about 3 minutes the PR shows a comment titled
**Changeset Sentinel: 🔴 CRITICAL risk** with SENT001 on `AppDatabase`, a snapshot command in
the rollback plan, and the `demo-review / sentinel / Change set review` check failing on
**Risk gate: failure**. Screenshot both.

---

## Step 7. Approve it like a change advisory board would

```bash
gh pr edit --add-label risk-accepted
```

**Success looks like:** the workflow reruns, the same comment updates to
**✅ Approved. Risk CRITICAL accepted by @TyroneMadison with label `risk-accepted`**, and the check
turns green. That line is your audit evidence. Screenshot it, then close the PR without merging:

```bash
gh pr close --delete-branch
git checkout main
```

---

## Step 8. Open a policy failure pull request (scenario 03)

```bash
git checkout -b demo/open-ssh
cp examples/scenarios/03-open-ssh-security-group/template.yaml examples/demo-stack/template.yaml
git commit -am "demo: open ssh for debugging"
git push -u origin demo/open-ssh
gh pr create --fill
```

**Success looks like:** HIGH risk with SENT004 naming `tcp port 22 from 0.0.0.0/0`, the Checks
table showing **Policy scan: failure** (cfn-guard `NO_OPEN_ADMIN_PORTS_INLINE`, Trivy critical),
and the check failing even if you add the label, because policy failures are not overridable.
Screenshot it, then close the PR the same way as Step 7.

---

## Step 9. Optional: try the anthropic provider locally

```bash
pip install -e ".[anthropic]"
python -m sentinel review --changeset examples/scenarios/04-iam-wildcard/changeset.json --provider anthropic
```

Requires `ANTHROPIC_API_KEY` in your environment. **Success looks like:** a report whose AI assessment row names `claude-sonnet-4-5` and a redaction count of 1.

---

## Step 10. Tear down

```bash
aws cloudformation delete-stack --region us-east-2 --stack-name sentinel-demo-app
aws cloudformation wait stack-delete-complete --region us-east-2 --stack-name sentinel-demo-app
aws rds describe-db-snapshots --region us-east-2 --snapshot-type manual --query "DBSnapshots[?contains(DBSnapshotIdentifier, 'sentinel-demo-app')].DBSnapshotIdentifier" --output text
```

Delete the final snapshot that `DeletionPolicy: Snapshot` left behind, and the retained bucket
(`DeletionPolicy: Retain` keeps it on purpose):

```bash
aws rds delete-db-snapshot --region us-east-2 --db-snapshot-identifier PASTE_SNAPSHOT_ID
aws s3 rb s3://PASTE_BUCKET_NAME --force
aws cloudformation delete-stack --region us-east-2 --stack-name changeset-sentinel-oidc
```

**Success looks like:** no stacks starting with `sentinel-` or `changeset-sentinel` in the
CloudFormation console. If you reviewed a brand new stack name at some point, an empty
`REVIEW_IN_PROGRESS` stack may remain; delete it the same way.

### What the demo costs

| Item | Rate (us-east-2, at time of writing, verify current) | Demo usage |
|---|---|---|
| RDS db.t4g.micro + 20 GB gp3 | about 0.02 USD per hour | 1 to 2 hours |
| Claude Sonnet 4.5 on Bedrock | 3 USD per M input tokens, 15 USD per M output | about 2 cents per review |
| S3, KMS AWS managed key, IAM, CloudFormation | free or fractions of a cent | |
| GitHub Actions | free for public repositories | |
