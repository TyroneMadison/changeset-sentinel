#!/usr/bin/env bash
# Scaffold a new service with a reviewed infrastructure pipeline.
#
#   scripts/new-service.sh <service-name> [target-repo-dir] [stack-prefix]
#
# Creates:
#   <target>/infra/<service-name>/template.yaml
#   <target>/.github/workflows/infra-review-<service-name>.yml
set -euo pipefail

NAME="${1:-}"
TARGET="${2:-.}"
PREFIX="${3:-sentinel-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/templates/new-service"

usage() {
  echo "usage: $0 <service-name> [target-repo-dir] [stack-prefix]" >&2
  exit 2
}

[[ -n "$NAME" ]] || usage
if [[ ! "$NAME" =~ ^[a-z][a-z0-9-]{1,38}$ ]]; then
  echo "service name must be lowercase letters, digits and dashes (2 to 39 chars)" >&2
  exit 2
fi
if [[ ! "$PREFIX" =~ ^[A-Za-z][A-Za-z0-9-]*$ ]]; then
  echo "stack prefix must start with a letter and use letters, digits and dashes" >&2
  exit 2
fi

INFRA_DIR="$TARGET/infra/$NAME"
WORKFLOW="$TARGET/.github/workflows/infra-review-$NAME.yml"
if [[ -e "$INFRA_DIR" || -e "$WORKFLOW" ]]; then
  echo "refusing to overwrite: $INFRA_DIR or $WORKFLOW already exists" >&2
  exit 1
fi

mkdir -p "$INFRA_DIR" "$(dirname "$WORKFLOW")"
sed "s/example-service/$NAME/g" "$SRC/infra/template.yaml" > "$INFRA_DIR/template.yaml"
sed -e "s/stack-name: sentinel-example-service/stack-name: ${PREFIX}example-service/" \
    -e "s/example-service/$NAME/g" \
    "$SRC/.github/workflows/infra-review.yml" > "$WORKFLOW"

cat <<MSG
Created:
  $INFRA_DIR/template.yaml
  $WORKFLOW

Next steps:
  1. Set the repository variable SENTINEL_ROLE_ARN to the role from bootstrap/github-oidc.yaml
     (deploy it with StackNamePrefix=$PREFIX).
  2. Commit both files and open a pull request.
  3. The PR gets a change set, policy checks and a risk report before anyone merges.
MSG
