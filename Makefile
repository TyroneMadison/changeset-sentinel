# changeset-sentinel developer and bootstrap tasks.
# Windows users: every target maps to a single command in docs/DEPLOY.md.

PYTHON  ?= python3
REGION  ?= us-east-2
ORG     ?= TyroneMadison
REPO    ?= changeset-sentinel
PREFIX  ?= sentinel-
OIDC_STACK ?= changeset-sentinel-oidc
DEMO_STACK ?= sentinel-demo-app
EXISTING_OIDC_ARN ?=

.PHONY: help install lint fmt test iac guard guard-negative scan allowlist demo ci \
        bootstrap-oidc role-arn deploy-demo-stack teardown-demo-stack teardown-oidc \
        new-service clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Install the package and dev tools
	$(PYTHON) -m pip install -r requirements-dev.txt -e .

lint: ## ruff lint and format check
	ruff check .
	ruff format --check .

fmt: ## Apply ruff formatting
	ruff format .
	ruff check --fix .

test: ## Unit tests
	$(PYTHON) -m pytest

iac: ## cfn-lint every template
	cfn-lint bootstrap/*.yaml examples/demo-stack/template.yaml examples/scenarios/*/template.yaml templates/new-service/infra/template.yaml

guard: ## cfn-guard org policy against the demo stack and starter template
	cfn-guard validate --data examples/demo-stack/template.yaml --rules policy/rules --show-summary fail
	cfn-guard validate --data templates/new-service/infra/template.yaml --rules policy/rules --show-summary fail

guard-negative: ## Prove the rules catch the insecure scenarios (03 open SSH, 04 admin wildcard)
	@for s in 03-open-ssh-security-group 04-iam-wildcard; do \
	  if cfn-guard validate --data examples/scenarios/$$s/template.yaml --rules policy/rules --show-summary none >/dev/null; then \
	    echo "expected a policy failure for $$s"; exit 1; \
	  else echo "caught: $$s"; fi; \
	done

scan: ## Checkov IaC scan
	checkov --config-file .checkov.yaml

allowlist: ## Check this repo against its own actions allowlist
	$(PYTHON) -m sentinel allowlist --policy policy/actions-allowlist.yml .github/workflows actions templates

demo: ## Offline demo over the recorded change sets
	$(PYTHON) -m sentinel demo --scenarios examples/scenarios --out out

ci: lint test iac allowlist demo ## Everything CI runs except checkov

bootstrap-oidc: ## Deploy the GitHub OIDC provider and review-only role
	aws cloudformation deploy --region $(REGION) --stack-name $(OIDC_STACK) \
	  --template-file bootstrap/github-oidc.yaml --capabilities CAPABILITY_IAM \
	  --parameter-overrides GitHubOrg=$(ORG) GitHubRepo=$(REPO) StackNamePrefix=$(PREFIX) \
	  ExistingOidcProviderArn=$(EXISTING_OIDC_ARN)

role-arn: ## Print the review role ARN
	aws cloudformation describe-stacks --region $(REGION) --stack-name $(OIDC_STACK) \
	  --query "Stacks[0].Outputs[?OutputKey=='RoleArn'].OutputValue" --output text

deploy-demo-stack: ## Create the demo app stack (edit examples/demo-stack/parameters.json first)
	aws cloudformation create-stack --region $(REGION) --stack-name $(DEMO_STACK) \
	  --template-body file://examples/demo-stack/template.yaml --capabilities CAPABILITY_IAM \
	  --parameters file://examples/demo-stack/parameters.json
	aws cloudformation wait stack-create-complete --region $(REGION) --stack-name $(DEMO_STACK)

teardown-demo-stack: ## Delete the demo app stack (RDS leaves a final snapshot, delete it too)
	aws cloudformation delete-stack --region $(REGION) --stack-name $(DEMO_STACK)
	aws cloudformation wait stack-delete-complete --region $(REGION) --stack-name $(DEMO_STACK)

teardown-oidc: ## Delete the OIDC role stack
	aws cloudformation delete-stack --region $(REGION) --stack-name $(OIDC_STACK)

new-service: ## Scaffold a service: make new-service NAME=billing-api TARGET=../my-repo
	scripts/new-service.sh $(NAME) $(or $(TARGET),.) $(PREFIX)

clean: ## Remove generated files
	rm -rf out .pytest_cache .ruff_cache build dist *.egg-info
