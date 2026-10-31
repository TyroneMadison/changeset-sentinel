#!/usr/bin/env bash
# Create a CloudFormation change set for review, save it as JSON, then delete it.
# This script never executes a change set. The IAM role it runs under cannot either.
set -euo pipefail

TEMPLATE_PATH="${INPUT_TEMPLATE_PATH:?template-path is required}"
STACK_NAME="${INPUT_STACK_NAME:?stack-name is required}"
PARAMS_FILE="${INPUT_PARAMETERS_FILE:-}"
OUT_FILE="${INPUT_OUTPUT_FILE:-${RUNNER_TEMP:-/tmp}/changeset.json}"
CS_NAME="sentinel-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"

if [[ ! -f "$TEMPLATE_PATH" ]]; then
  echo "::error::Template not found: $TEMPLATE_PATH"
  exit 1
fi

cleanup() {
  aws cloudformation delete-change-set \
    --stack-name "$STACK_NAME" --change-set-name "$CS_NAME" >/dev/null 2>&1 || true
  echo "Change set $CS_NAME deleted (review only, never executed)."
}
trap cleanup EXIT

# UPDATE when the stack exists. CREATE for new stacks and for stacks still in
# REVIEW_IN_PROGRESS from an earlier review of a brand new stack.
STATUS="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo NONE)"
if [[ "$STATUS" == "NONE" || "$STATUS" == "REVIEW_IN_PROGRESS" ]]; then
  CS_TYPE=CREATE
else
  CS_TYPE=UPDATE
fi
echo "Stack $STACK_NAME status: $STATUS. Change set type: $CS_TYPE."

args=(
  --stack-name "$STACK_NAME"
  --change-set-name "$CS_NAME"
  --change-set-type "$CS_TYPE"
  --template-body "file://${TEMPLATE_PATH}"
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
  --description "changeset-sentinel review for run ${GITHUB_RUN_ID:-local}"
)
if [[ -n "$PARAMS_FILE" ]]; then
  args+=(--parameters "file://${PARAMS_FILE}")
fi

aws cloudformation create-change-set "${args[@]}" >/dev/null

if ! aws cloudformation wait change-set-create-complete \
  --stack-name "$STACK_NAME" --change-set-name "$CS_NAME"; then
  REASON="$(aws cloudformation describe-change-set --stack-name "$STACK_NAME" \
    --change-set-name "$CS_NAME" --query StatusReason --output text)"
  if [[ "$REASON" == *"didn't contain changes"* || "$REASON" == *"No updates are to be performed"* ]]; then
    echo "No changes: $REASON"
  else
    echo "::error::Change set failed: $REASON"
    exit 1
  fi
fi

# The CLI paginates DescribeChangeSet and merges Changes for us.
aws cloudformation describe-change-set \
  --stack-name "$STACK_NAME" --change-set-name "$CS_NAME" \
  --include-property-values --output json > "$OUT_FILE"

COUNT="$(jq '.Changes | length' "$OUT_FILE")"
echo "Saved $COUNT resource change(s) to $OUT_FILE"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "changeset-file=$OUT_FILE"
    echo "change-count=$COUNT"
    echo "changeset-type=$CS_TYPE"
  } >> "$GITHUB_OUTPUT"
fi
