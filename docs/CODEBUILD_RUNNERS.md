# Running on CodeBuild managed runners

GitHub hosted runners work out of the box. Platform teams often prefer AWS CodeBuild
managed runners: the job runs inside your account, can reach private VPC resources, and
you control the image and the compute size.

## How it plugs in

The reusable workflow takes a `runs-on` input. CodeBuild picks up jobs whose label
matches its project name:

```yaml
jobs:
  sentinel:
    uses: TyroneMadison/changeset-sentinel/.github/workflows/sentinel-review.yml@v1
    permissions:
      id-token: write
      contents: read
      pull-requests: write
      issues: read
    with:
      template-path: infra/template.yaml
      stack-name: sentinel-demo-app
      role-to-assume: ${{ vars.SENTINEL_ROLE_ARN }}
      runs-on: codebuild-sentinel-runner-${{ github.run_id }}-${{ github.run_attempt }}
```

## One-time setup

1. Connect CodeBuild to GitHub (Developer Tools, Connections) or use a GitHub App.
2. Create a CodeBuild project named `sentinel-runner` with the GitHub repository as source.
3. Add a webhook filter group with event type `WORKFLOW_JOB_QUEUED`.
4. Pick an image with Python 3.12, Rust (for cfn-guard) and the AWS CLI, for example the
   standard Amazon Linux image. The workflow installs everything else.

## What changes and what does not

| Item | GitHub hosted | CodeBuild managed |
|---|---|---|
| Where the job runs | GitHub infrastructure | Your AWS account |
| AWS credentials | OIDC role from `bootstrap/github-oidc.yaml` | Same OIDC role, so permissions stay identical |
| Private VPC access | No | Yes, if the project is VPC attached |
| Cost | Free for public repos | CodeBuild per minute pricing |

Keeping OIDC on CodeBuild runners means the review role stays the single source of truth
for what the pipeline may do, wherever the job runs.
