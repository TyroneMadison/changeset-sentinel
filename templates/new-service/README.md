# New service scaffold

`scripts/new-service.sh` copies these files into a target repository so a new
service starts with infrastructure as code and a reviewed pipeline on day one.

| File | Lands at | Purpose |
|---|---|---|
| `infra/template.yaml` | `infra/<name>/template.yaml` | Starter stack: encrypted SQS queue with DLQ, log group with retention, least privilege role |
| `.github/workflows/infra-review.yml` | `.github/workflows/infra-review-<name>.yml` | Calls the reusable sentinel-review workflow on every PR that touches the service |

The placeholder `example-service` is replaced with the new service name, and the stack name prefix `sentinel-` with the prefix you pass.
