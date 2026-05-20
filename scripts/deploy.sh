#!/usr/bin/env bash
# Full deployment script for the Pipeline Integrity Agent.
#
# Orchestrates:
#   1. CloudFormation stack deploy (infrastructure)
#   2. Data upload to S3 + DynamoDB population
#   3. Knowledge Base sync (index PDFs)
#   4. AgentCore configure + deploy (agent runtime)
#
# Usage:
#   ./scripts/deploy.sh [--stack-name NAME] [--region REGION]
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Python 3.11+ with boto3 installed
#   - AgentCore CLI installed (pip install bedrock-agentcore)

set -euo pipefail

# ============================================================
# Configuration defaults
# ============================================================
STACK_NAME="${STACK_NAME:-pipeline-integrity-agent}"
REGION="${REGION:-us-west-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Parse optional CLI arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --stack-name) STACK_NAME="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "============================================"
echo "Pipeline Integrity Agent — Full Deployment"
echo "============================================"
echo "Stack Name : ${STACK_NAME}"
echo "Region     : ${REGION}"
echo "Project    : ${PROJECT_ROOT}"
echo ""

# ============================================================
# Step 1: Deploy CloudFormation infrastructure
# ============================================================
echo "--- Step 1/4: Deploying CloudFormation stack ---"

aws cloudformation deploy \
    --template-file "${PROJECT_ROOT}/infrastructure/template.yaml" \
    --stack-name "${STACK_NAME}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "${REGION}" \
    --no-cli-pager \
    --no-fail-on-empty-changeset

echo "  CloudFormation stack deployed successfully."
echo ""

# ============================================================
# Step 2: Upload data files to S3 and populate DynamoDB
# ============================================================
echo "--- Step 2/4: Uploading data to S3 and DynamoDB ---"

python3 "${SCRIPT_DIR}/upload_data.py" \
    --stack-name "${STACK_NAME}" \
    --region "${REGION}"

echo ""

# ============================================================
# Step 3: Sync Knowledge Base (index uploaded PDFs)
# ============================================================
echo "--- Step 3/4: Syncing Knowledge Base ---"

python3 "${SCRIPT_DIR}/sync_knowledge_base.py" \
    --stack-name "${STACK_NAME}" \
    --region "${REGION}"

echo ""

# ============================================================
# Step 4: Configure and deploy agent to AgentCore Runtime
# ============================================================
echo "--- Step 4/4: Deploying agent to AgentCore Runtime ---"

cd "${PROJECT_ROOT}/agent"

# Configure the agent entrypoint for AgentCore
agentcore configure -e agent.py --non-interactive

# Deploy the agent (builds container, pushes to ECR, creates/updates runtime)
agentcore deploy

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  - Invoke the agent: agentcore invoke --payload '{...}'"
echo "  - Run test scenarios: python scripts/test_agent.py"
echo "  - View logs: agentcore logs"
