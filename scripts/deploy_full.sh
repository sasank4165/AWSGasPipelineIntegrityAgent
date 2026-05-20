#!/usr/bin/env bash
# =============================================================================
# Full Deployment Script — Pipeline Integrity Agent
# =============================================================================
# Replicates the complete deployment sequence from scratch.
# Run from the project root directory.
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Python 3.11+ with boto3, opensearch-py installed
#   - AgentCore CLI installed (pip install bedrock-agentcore)
#   - pip install opensearch-py
#
# Usage:
#   ./scripts/deploy_full.sh
#
# This script is idempotent — safe to re-run (uses --no-fail-on-empty-changeset).
# =============================================================================

set -euo pipefail

REGION="us-west-2"
STACK_NAME="pipeline-integrity-agent"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --no-cli-pager)

echo "============================================"
echo "Pipeline Integrity Agent — Full Deployment"
echo "============================================"
echo "Account  : ${ACCOUNT_ID}"
echo "Region   : ${REGION}"
echo "Stack    : ${STACK_NAME}"
echo ""

# =============================================================================
# STEP 1: Create artifacts bucket and upload Lambda code
# =============================================================================
echo "--- Step 1: Package and upload Lambda code ---"

ARTIFACTS_BUCKET="${STACK_NAME}-artifacts-${ACCOUNT_ID}"
aws s3 mb "s3://${ARTIFACTS_BUCKET}" --region "${REGION}" --no-cli-pager 2>/dev/null || true

# Package Lambda functions
mkdir -p /tmp/lambda-packages
zip -j /tmp/lambda-packages/scada_query.zip lambdas/scada_query/handler.py
zip -j /tmp/lambda-packages/incident_mgmt.zip lambdas/incident_mgmt/handler.py

# Upload to S3
aws s3 cp /tmp/lambda-packages/scada_query.zip "s3://${ARTIFACTS_BUCKET}/lambdas/scada_query.zip" --region "${REGION}" --no-cli-pager
aws s3 cp /tmp/lambda-packages/incident_mgmt.zip "s3://${ARTIFACTS_BUCKET}/lambdas/incident_mgmt.zip" --region "${REGION}" --no-cli-pager

echo "  Lambda code uploaded to s3://${ARTIFACTS_BUCKET}/lambdas/"
echo ""

# =============================================================================
# STEP 2: Deploy CloudFormation stack (core infrastructure)
# =============================================================================
echo "--- Step 2: Deploy CloudFormation stack ---"

aws cloudformation deploy \
    --template-file "${PROJECT_ROOT}/infrastructure/template-core.yaml" \
    --stack-name "${STACK_NAME}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "${REGION}" \
    --no-cli-pager \
    --no-fail-on-empty-changeset

echo "  Stack deployed."
echo ""

# =============================================================================
# STEP 3: Upload data to S3 and populate DynamoDB
# =============================================================================
echo "--- Step 3: Upload data ---"

python3 "${PROJECT_ROOT}/scripts/upload_data.py" \
    --stack-name "${STACK_NAME}" \
    --region "${REGION}"

echo ""

# =============================================================================
# STEP 4: Deploy agent to AgentCore Runtime
# =============================================================================
echo "--- Step 4: Deploy agent to AgentCore Runtime ---"

export AGENTCORE_SUPPRESS_RECOMMENDATION=1

agentcore configure \
    -e agent/agent.py \
    -n pipeline_integrity_agent \
    -dt direct_code_deploy \
    -rt PYTHON_3_13 \
    -r "${REGION}" \
    -ni

agentcore deploy -auc

echo "  Agent deployed."
echo ""

# =============================================================================
# STEP 5: Create AgentCore Gateway with AWS_IAM auth
# =============================================================================
echo "--- Step 5: Create AgentCore Gateway ---"

python3 -c "
import boto3, json, time

client = boto3.client('bedrock-agentcore-control', region_name='${REGION}')
iam = boto3.client('iam', region_name='${REGION}')

# Create gateway execution role
role_name = 'AgentCoreGatewayExecutionRole'
try:
    iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps({
            'Version': '2012-10-17',
            'Statement': [{'Effect': 'Allow', 'Principal': {'Service': 'bedrock-agentcore.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]
        })
    )
except iam.exceptions.EntityAlreadyExistsException:
    pass

# Add Lambda invoke permission to gateway role
iam.put_role_policy(
    RoleName=role_name,
    PolicyName='InvokePipelineLambdas',
    PolicyDocument=json.dumps({
        'Version': '2012-10-17',
        'Statement': [{'Effect': 'Allow', 'Action': 'lambda:InvokeFunction', 'Resource': 'arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${STACK_NAME}-*'}]
    })
)

role_arn = f'arn:aws:iam::${ACCOUNT_ID}:role/{role_name}'
time.sleep(10)  # Wait for IAM propagation

# Create gateway
response = client.create_gateway(
    name='pipeline-tools',
    roleArn=role_arn,
    protocolType='MCP',
    authorizerType='AWS_IAM',
    protocolConfiguration={'mcp': {'searchType': 'SEMANTIC'}},
    exceptionLevel='DEBUG'
)
gateway_id = response['gatewayId']
gateway_url = response['gatewayUrl']
print(f'Gateway created: {gateway_id}')
print(f'Gateway URL: {gateway_url}')

# Wait for READY
for i in range(12):
    time.sleep(5)
    gw = client.get_gateway(gatewayIdentifier=gateway_id)
    if gw['status'] == 'READY':
        break

# Put resource policy to allow agent to invoke
client.put_resource_policy(
    resourceArn=f'arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:gateway/{gateway_id}',
    policy=json.dumps({
        'Version': '2012-10-17',
        'Statement': [{'Effect': 'Allow', 'Principal': {'AWS': 'arn:aws:iam::${ACCOUNT_ID}:root'}, 'Action': 'bedrock-agentcore:InvokeGateway', 'Resource': f'arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:gateway/{gateway_id}'}]
    })
)

# Create SCADA Query target
client.create_gateway_target(
    gatewayIdentifier=gateway_id,
    name='ScadaQuery',
    targetConfiguration={'mcp': {'lambda': {'lambdaArn': 'arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${STACK_NAME}-scada-query-dev', 'toolSchema': {'inlinePayload': [
        {'name': 'query_scada_readings', 'description': 'Query SCADA telemetry readings for stations within a time range.', 'inputSchema': {'type': 'object', 'properties': {'station_ids': {'type': 'array', 'items': {'type': 'string'}}, 'start_time': {'type': 'string'}, 'end_time': {'type': 'string'}, 'limit': {'type': 'integer'}}, 'required': ['station_ids', 'start_time', 'end_time']}},
        {'name': 'check_compressor_events', 'description': 'Check for compressor events at stations within a time window.', 'inputSchema': {'type': 'object', 'properties': {'station_ids': {'type': 'array', 'items': {'type': 'string'}}, 'start_time': {'type': 'string'}, 'end_time': {'type': 'string'}}, 'required': ['station_ids', 'start_time', 'end_time']}},
        {'name': 'check_valve_changes', 'description': 'Check for valve position changes at stations.', 'inputSchema': {'type': 'object', 'properties': {'station_ids': {'type': 'array', 'items': {'type': 'string'}}, 'start_time': {'type': 'string'}, 'end_time': {'type': 'string'}}, 'required': ['station_ids', 'start_time', 'end_time']}},
        {'name': 'query_station_metadata', 'description': 'Query pipeline segment metadata.', 'inputSchema': {'type': 'object', 'properties': {'segment_id': {'type': 'string'}, 'station_id': {'type': 'string'}}}}
    ]}}}},
    credentialProviderConfigurations=[{'credentialProviderType': 'GATEWAY_IAM_ROLE'}]
)
print('ScadaQuery target created')

# Create Incident Mgmt target
client.create_gateway_target(
    gatewayIdentifier=gateway_id,
    name='IncidentMgmt',
    targetConfiguration={'mcp': {'lambda': {'lambdaArn': 'arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${STACK_NAME}-incident-mgmt-dev', 'toolSchema': {'inlinePayload': [
        {'name': 'create_incident', 'description': 'Create an incident record after confirming a leak.', 'inputSchema': {'type': 'object', 'properties': {'classification': {'type': 'string'}, 'affected_segment': {'type': 'string'}, 'affected_stations': {'type': 'array', 'items': {'type': 'string'}}, 'anomaly_analysis': {'type': 'object'}, 'false_positive_check': {'type': 'object'}, 'severity': {'type': 'string'}, 'leak_rate_mmscfd': {'type': 'number'}, 'phmsa_reportable': {'type': 'boolean'}, 'recommended_actions': {'type': 'array', 'items': {'type': 'string'}}, 'response_time_seconds': {'type': 'integer'}}, 'required': ['classification', 'affected_segment', 'affected_stations', 'anomaly_analysis', 'false_positive_check', 'recommended_actions', 'response_time_seconds']}},
        {'name': 'send_alert', 'description': 'Publish alert to SNS control room topic.', 'inputSchema': {'type': 'object', 'properties': {'incident_id': {'type': 'string'}, 'severity': {'type': 'string'}, 'affected_segment': {'type': 'string'}, 'leak_location': {'type': 'string'}, 'recommended_actions': {'type': 'array', 'items': {'type': 'string'}}, 'phmsa_reportable': {'type': 'boolean'}, 'summary': {'type': 'string'}}, 'required': ['incident_id', 'severity', 'affected_segment', 'leak_location', 'recommended_actions', 'phmsa_reportable', 'summary']}}
    ]}}}},
    credentialProviderConfigurations=[{'credentialProviderType': 'GATEWAY_IAM_ROLE'}]
)
print('IncidentMgmt target created')

# Add gateway invoke permission to agent's execution role
roles = iam.list_roles(MaxItems=100)['Roles']
agent_role = next((r for r in roles if 'AmazonBedrockAgentCoreSDKRuntime' in r['RoleName']), None)
if agent_role:
    iam.put_role_policy(
        RoleName=agent_role['RoleName'],
        PolicyName='InvokeGateway',
        PolicyDocument=json.dumps({'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': ['bedrock-agentcore:InvokeGateway', 'bedrock-agentcore:InvokeAgentRuntime'], 'Resource': '*'}]})
    )
    print(f'Added InvokeGateway policy to {agent_role[\"RoleName\"]}')

# Save gateway URL for agent redeploy
with open('/tmp/gateway_url.txt', 'w') as f:
    f.write(gateway_url)
print(f'GATEWAY_URL={gateway_url}')
"

echo ""

# =============================================================================
# STEP 6: Redeploy agent with Gateway URL
# =============================================================================
echo "--- Step 6: Redeploy agent with Gateway URL ---"

GATEWAY_URL=$(cat /tmp/gateway_url.txt)
agentcore deploy -auc --env "GATEWAY_URL=${GATEWAY_URL}" --env "AWS_DEFAULT_REGION=${REGION}"

echo ""

# =============================================================================
# STEP 7: Create Knowledge Base (OpenSearch Serverless + Bedrock KB)
# =============================================================================
echo "--- Step 7: Create Knowledge Base ---"

python3 "${PROJECT_ROOT}/scripts/create_knowledge_base.py" --region "${REGION}" --account-id "${ACCOUNT_ID}"

echo ""

# =============================================================================
# STEP 8: Create SageMaker Studio for dashboard (optional)
# =============================================================================
echo "--- Step 8: SageMaker Studio setup ---"
echo "  Skipping SageMaker Studio (run manually if needed)."
echo "  To run dashboard locally instead:"
echo "    pip install -r dashboard/requirements.txt"
echo "    streamlit run dashboard/app.py --server.port 8501"
echo ""

# =============================================================================
# STEP 9: Add SageMaker role permissions for agent invocation
# =============================================================================
echo "--- Step 9: Add SageMaker role permissions ---"

python3 -c "
import boto3, json

iam = boto3.client('iam', region_name='${REGION}')

# If a SageMaker Studio role exists, grant it full dashboard permissions:
# - S3 read/write (for live SCADA simulation)
# - DynamoDB read (for incidents/segments)
# - AgentCore invoke (for simulate anomaly page)
role_name = 'pipeline-integrity-sagemaker-role'
try:
    iam.get_role(RoleName=role_name)

    # S3 + DynamoDB access for dashboard data
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName='DashboardDataAccess',
        PolicyDocument=json.dumps({
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Effect': 'Allow',
                    'Action': ['s3:GetObject', 's3:ListBucket', 's3:PutObject'],
                    'Resource': [
                        'arn:aws:s3:::${STACK_NAME}-data-${ACCOUNT_ID}-dev',
                        'arn:aws:s3:::${STACK_NAME}-data-${ACCOUNT_ID}-dev/*'
                    ]
                },
                {
                    'Effect': 'Allow',
                    'Action': ['dynamodb:GetItem', 'dynamodb:Scan', 'dynamodb:Query'],
                    'Resource': 'arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${STACK_NAME}-*'
                }
            ]
        })
    )
    print(f'Added DashboardDataAccess policy to {role_name}')

    # AgentCore invoke permission for simulate anomaly page
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName='InvokeAgentCore',
        PolicyDocument=json.dumps({
            'Version': '2012-10-17',
            'Statement': [{
                'Effect': 'Allow',
                'Action': [
                    'bedrock-agentcore:InvokeAgentRuntime',
                    'bedrock-agentcore:StopRuntimeSession'
                ],
                'Resource': '*'
            }]
        })
    )
    print(f'Added InvokeAgentCore policy to {role_name}')

except iam.exceptions.NoSuchEntityException:
    print(f'SageMaker role {role_name} not found — skipping (create Studio first)')
"

echo ""

# =============================================================================
# DONE
# =============================================================================
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo ""
echo "Resources deployed:"
echo "  - CloudFormation stack: ${STACK_NAME}"
echo "  - S3 bucket: ${STACK_NAME}-data-${ACCOUNT_ID}-dev"
echo "  - DynamoDB tables: PipelineSegments, ValveStatus, Incidents"
echo "  - Lambda: ${STACK_NAME}-scada-query-dev"
echo "  - Lambda: ${STACK_NAME}-incident-mgmt-dev"
echo "  - AgentCore Runtime: pipeline_integrity_agent"
echo "  - AgentCore Gateway: pipeline-tools (AWS_IAM auth)"
echo "  - Knowledge Base: pipeline-integrity-kb"
echo ""
echo "Test the agent:"
echo "  agentcore invoke '{\"prompt\": \"Hello, what is your role?\"}'"
echo ""
echo "Run full leak scenario:"
echo "  python3 scripts/demo_invoke.py --local"
