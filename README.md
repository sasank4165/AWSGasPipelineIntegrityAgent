# Pipeline Integrity Agent
## Autonomous Leak Detection with Amazon Bedrock AgentCore

An AI agent that monitors SCADA telemetry from 8 stations across a 200-mile natural gas pipeline, detects leaks through contextual reasoning, disambiguates false positives, and orchestrates incident response.

Built with **Strands Agents SDK** on **Amazon Bedrock AgentCore**.

---

## The Problem

Traditional pipeline monitoring uses fixed-threshold SCADA alarms that generate excessive false positives:
- Compressor starts cause 15-25 PSI pressure swings
- Valve repositioning creates 8-15 PSI redistribution  
- Overnight temperature drops mimic small leak signatures
- Operators face alarm fatigue — real leaks get lost in noise

**Result:** Missed leaks cause environmental damage, regulatory fines, and safety risk. False alarms cause unnecessary shutdowns costing $100K+ per event.

---

## The Solution

An autonomous agent that doesn't just detect anomalies — it **investigates** them using a 5-step reasoning workflow:

1. **Anomaly Analysis** — Query SCADA data, quantify deviation from normal
2. **False Positive Disambiguation** — Check compressor events, valve changes, temperature effects
3. **Leak Localization** — Estimate mile marker using pressure gradient analysis
4. **Severity Assessment** — Classify leak rate, check PHMSA reporting thresholds
5. **Incident Response** — Create record, send alerts, recommend valve closures

The agent completes a full investigation in **1-3 minutes** with 98% detection accuracy.

---

## Architecture

```
+------------------------------------------------------------------+
|                    Amazon Bedrock AgentCore                        |
|                                                                    |
|  +----------------+  +----------------+  +---------------------+  |
|  | Runtime        |  | Memory (STM)   |  | Code Interpreter    |  |
|  | (Agent Host)   |  | (Sessions +    |  | (Physics Calcs:     |  |
|  | Claude Sonnet 4|  |  Baselines)    |  |  Mass Balance,      |  |
|  +-------+--------+  +----------------+  |  Pressure Gradient) |  |
|          |                                +---------------------+  |
|  +-------+--------+                                               |
|  | Gateway (MCP)  | <-- AWS_IAM auth                              |
|  +-------+--------+                                               |
+---------+------------------------------------------------------------+
          |
    +-----+----------------------------+
    |         Lambda Tools              |
    |  +-----------+  +--------------+  |
    |  | SCADA     |  | Incident     |  |
    |  | Query     |  | Management   |  |
    |  +-----+-----+  +------+-------+  |
    +-------+----------------+-----------+
            |                |
    +-------+----+    +------+------+    +------------------+
    | S3 Bucket  |    | DynamoDB    |    | Bedrock KB       |
    | (SCADA CSV)|    | (Incidents, |    | (Operating Procs |
    |            |    |  Segments)  |    |  + PHMSA Regs)   |
    +------------+    +-------------+    +------------------+
```

---

## Pipeline System

| Parameter | Value |
|-----------|-------|
| Length | 200 miles |
| Diameter | 24 inches |
| Material | API 5L X65 steel |
| MAOP | 850 PSI |
| Normal Pressure | 700-800 PSI |
| Normal Flow | 5.5-6.5 MMSCFD |
| Stations | 8 (ST-01 to ST-08) |
| Segments | 7 (SEG-01 to SEG-07) |
| Isolation Valves | 16 remotely operable |

---

## Technology Stack

| Component | Service | Purpose |
|-----------|---------|---------|
| Agent Runtime | Bedrock AgentCore Runtime | Serverless agent hosting |
| Agent Model | Claude Sonnet 4 (us.anthropic.claude-sonnet-4-20250514-v1:0) | Multi-step reasoning |
| Tool Gateway | AgentCore Gateway (MCP, AWS_IAM) | Lambda tool exposure |
| SCADA Query | AWS Lambda + pandas | Read telemetry from S3 |
| Incident Mgmt | AWS Lambda | Create incidents, send SNS alerts |
| Physics Engine | AgentCore Code Interpreter | Mass balance, pressure gradient calcs |
| Knowledge Base | Bedrock KB + OpenSearch Serverless | Operating procedures, PHMSA regs |
| Memory | AgentCore Memory (STM) | Session persistence |
| Data Lake | Amazon S3 | SCADA CSV, gas composition, weather |
| Metadata Store | Amazon DynamoDB | Segments, valves, incidents |
| Alerts | Amazon SNS | Control room notifications |
| Dashboard | Streamlit on SageMaker Studio | Real-time monitoring UI |
| Agent Framework | Strands Agents SDK | @tool decorator pattern |
| Deployment CLI | AgentCore CLI | Configure + deploy |

---

## Prerequisites

Before deploying, ensure you have:

1. **AWS Account** with the following enabled:
   - Bedrock model access for Claude Sonnet 4 in us-west-2
   - Sufficient service quotas for Lambda, DynamoDB, S3, OpenSearch Serverless

2. **Local tools installed:**
   ```bash
   # Python 3.11+
   python3 --version

   # AWS CLI configured
   aws sts get-caller-identity

   # AgentCore CLI
   pip install bedrock-agentcore
   agentcore --help

   # Additional Python packages
   pip install boto3 opensearch-py pandas
   ```

3. **IAM permissions** — your AWS credentials need:
   - CloudFormation (create stacks, IAM roles)
   - S3 (create buckets, upload objects)
   - DynamoDB (create tables, write items)
   - Lambda (create functions, invoke)
   - Bedrock (create KB, invoke models)
   - OpenSearch Serverless (create collections, policies)
   - SageMaker (create domains — optional, for dashboard)
   - IAM (create roles, policies)

---

## Deployment

### One-Command Deploy

```bash
git clone <this-repo>
cd pipeline-leak-detection
pip install boto3 opensearch-py bedrock-agentcore
./scripts/deploy_full.sh
```

Total time: ~10-15 minutes.

### What deploy_full.sh Does

| Step | Action | Time |
|------|--------|------|
| 1 | Create S3 artifacts bucket, package + upload Lambda zips | 30s |
| 2 | Deploy CloudFormation stack (S3, DynamoDB, Lambda, SNS, IAM) | 2-3 min |
| 3 | Upload SCADA data to S3, populate DynamoDB tables | 1 min |
| 4 | Configure + deploy agent to AgentCore Runtime | 2-3 min |
| 5 | Create AgentCore Gateway + Lambda targets + IAM permissions | 1-2 min |
| 6 | Redeploy agent with Gateway URL environment variable | 1-2 min |
| 7 | Create Knowledge Base (OpenSearch collection + Bedrock KB + sync) | 3-5 min |
| 8 | (Optional) SageMaker Studio setup | Manual |
| 9 | Add SageMaker role permissions (if Studio exists) | 10s |

### Manual Step-by-Step

If the one-command deploy fails or you need to debug, see each step below.

#### Step 1: Package Lambda Code

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ARTIFACTS_BUCKET="pipeline-integrity-agent-artifacts-${ACCOUNT_ID}"

aws s3 mb "s3://${ARTIFACTS_BUCKET}" --region us-west-2
zip -j /tmp/scada_query.zip lambdas/scada_query/handler.py
zip -j /tmp/incident_mgmt.zip lambdas/incident_mgmt/handler.py
aws s3 cp /tmp/scada_query.zip "s3://${ARTIFACTS_BUCKET}/lambdas/scada_query.zip"
aws s3 cp /tmp/incident_mgmt.zip "s3://${ARTIFACTS_BUCKET}/lambdas/incident_mgmt.zip"
```

#### Step 2: Deploy CloudFormation

```bash
aws cloudformation deploy \
    --template-file infrastructure/template-core.yaml \
    --stack-name pipeline-integrity-agent \
    --capabilities CAPABILITY_NAMED_IAM \
    --region us-west-2 --no-cli-pager
```

**Note:** We use `template-core.yaml` (not `template.yaml`) because the Knowledge Base has an ordering dependency that CloudFormation can't handle (OpenSearch index must exist before KB creation). The KB is created separately in Step 7.

#### Step 3: Upload Data

```bash
python3 scripts/upload_data.py --stack-name pipeline-integrity-agent --region us-west-2
```

This uploads:
- 10 CSV files to S3 (SCADA telemetry, gas composition, weather, etc.)
- 2 PDF files to `knowledge-base/` prefix (operating procedures, PHMSA regulations)
- 7 pipeline segments to DynamoDB
- 1890 valve status records to DynamoDB

#### Step 4: Deploy Agent

```bash
export AGENTCORE_SUPPRESS_RECOMMENDATION=1

agentcore configure \
    -e agent/agent.py \
    -n pipeline_integrity_agent \
    -dt direct_code_deploy \
    -rt PYTHON_3_13 \
    -r us-west-2 -ni

agentcore deploy -auc
```

Note the **Agent ARN** and **Memory ID** from the output — you'll need them later.

#### Step 5: Create Gateway

Run the Python script in `deploy_full.sh` Step 5, or use:

```bash
# See scripts/deploy_full.sh Step 5 for the full Python script
# Key outputs needed: GATEWAY_URL
```

The gateway:
- Uses AWS_IAM authorization (compatible with the agent's SigV4 client)
- Has two Lambda targets: ScadaQuery (4 tools) and IncidentMgmt (2 tools)
- Has a resource policy allowing the account to invoke it
- The agent's execution role gets `bedrock-agentcore:InvokeGateway` permission

#### Step 6: Redeploy Agent with Gateway URL

```bash
GATEWAY_URL="https://<gateway-id>.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"
MEMORY_ID="<from agentcore status>"

agentcore deploy -auc \
    --env "GATEWAY_URL=${GATEWAY_URL}" \
    --env "AWS_DEFAULT_REGION=us-west-2" \
    --env "AGENTCORE_MEMORY_ID=${MEMORY_ID}"
```

#### Step 7: Create Knowledge Base

```bash
python3 scripts/create_knowledge_base.py --region us-west-2 --account-id ${ACCOUNT_ID}
```

This script handles the ordering that CloudFormation can't:
1. Creates IAM role for KB
2. Creates OpenSearch Serverless encryption/network/access policies
3. Creates VECTORSEARCH collection (waits ~3-5 min for ACTIVE)
4. Creates vector index via OpenSearch API (1024 dimensions for Titan Embed v2)
5. Creates Bedrock Knowledge Base pointing to the index
6. Creates S3 data source and triggers ingestion (indexes 2 PDFs)

#### Step 8: Test

```bash
# Quick test
agentcore invoke '{"prompt": "Hello, what is your role?"}'

# Full leak investigation
agentcore invoke '{"event_id": "TEST-001", "timestamp": "2025-12-04T23:55:00Z", "anomaly_type": "mass_balance_deficit", "affected_stations": ["ST-05", "ST-06"], "affected_segment": "SEG-05", "trigger_values": {"pressure_drop_psi": 18.0, "mass_balance_deficit_mmscfd": 1.2}, "severity": "critical"}'

# False positive scenario
agentcore invoke '{"event_id": "TEST-FP", "timestamp": "2025-12-10T06:30:00Z", "anomaly_type": "pressure_drop", "affected_stations": ["ST-03", "ST-04"], "affected_segment": "SEG-03", "trigger_values": {"pressure_drop_psi": 8.5, "duration_minutes": 12, "mass_balance_deficit_mmscfd": 0.28}, "severity": "warning"}'
```

---

## Dashboard

### Option A: Run Locally

```bash
pip install streamlit plotly pandas boto3 streamlit-autorefresh
export SCADA_BUCKET=pipeline-integrity-agent-data-<ACCOUNT_ID>-dev
export INCIDENTS_TABLE=pipeline-integrity-agent-Incidents-dev
export SEGMENTS_TABLE=pipeline-integrity-agent-PipelineSegments-dev
export VALVE_TABLE=pipeline-integrity-agent-ValveStatus-dev
streamlit run dashboard/app.py --server.port 8501
```

### Option B: SageMaker Studio

1. Create Studio domain + user profile + JupyterLab space
2. Add IAM permissions to the SageMaker execution role:
   - `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the data bucket
   - `dynamodb:GetItem`, `dynamodb:Scan` on pipeline tables
   - `bedrock-agentcore:InvokeAgentRuntime` (for simulate anomaly page)
3. In Studio terminal:
   ```bash
   aws s3 cp s3://pipeline-integrity-agent-data-<ACCOUNT_ID>-dev/dashboard/ ./dashboard/ --recursive
   pip install streamlit plotly pandas boto3 streamlit-autorefresh
   cd dashboard
   streamlit run app.py --server.port 8501 --server.headless true
   ```
4. Access at: `https://<domain>.studio.us-west-2.sagemaker.aws/jupyterlab/default/proxy/8501/`

### Live SCADA Simulation

To make the Pipeline Overview show changing data:

```bash
# In a separate terminal (Studio or local)
python3 simulate_live_scada.py --speed 10 --interval 5
```

This replays the SCADA CSV at 10x speed, writing a rolling window to S3 every 5 seconds.

### Dashboard Pages

| Page | Purpose |
|------|---------|
| **App (Home)** | Project overview, architecture, how-to-demo guide |
| **Pipeline Overview** | Live station gauges, segment health map, auto-refresh |
| **Active Incidents** | Filterable incident table with expandable reasoning |
| **Incident Detail** | Single incident deep-dive with step-by-step timeline |
| **Historical Trends** | Time-series charts (pressure, flow, deficit) |
| **Simulate Anomaly** | Trigger pre-built or custom scenarios |

---

## Project Structure

```
pipeline-leak-detection/
├── agent/
│   ├── agent.py              # Main entrypoint (Strands + AgentCore Runtime)
│   ├── tools.py              # @tool functions (physics + memory)
│   ├── prompts.py            # System prompt (5-step workflow)
│   ├── models.py             # Dataclasses (AnomalyEvent, IncidentReport, etc.)
│   └── requirements.txt      # Runtime dependencies
├── lambdas/
│   ├── scada_query/
│   │   └── handler.py        # SCADA query Lambda (4 tools)
│   ├── incident_mgmt/
│   │   └── handler.py        # Incident management Lambda (2 tools)
│   └── tests/                # Unit tests (pytest)
├── dashboard/
│   ├── app.py                # Streamlit main page
│   ├── utils.py              # Data helpers (S3/DynamoDB)
│   ├── simulate_live_scada.py # Live data replay
│   ├── setup_studio.sh       # SageMaker Studio setup script
│   ├── requirements.txt      # Dashboard dependencies
│   └── pages/
│       ├── 1_pipeline_overview.py
│       ├── 2_active_incidents.py
│       ├── 3_incident_detail.py
│       ├── 4_historical_trends.py
│       └── 5_simulate_anomaly.py
├── infrastructure/
│   ├── template-core.yaml    # CloudFormation (S3, DDB, Lambda, SNS, IAM)
│   └── template.yaml         # Full template (includes KB — has ordering issue)
├── scripts/
│   ├── deploy_full.sh        # One-command deployment
│   ├── upload_data.py        # Data upload to S3/DynamoDB
│   ├── create_knowledge_base.py  # KB + OpenSearch setup
│   ├── simulate_live_scada.py    # Live SCADA replay
│   ├── demo_invoke.py        # Single scenario demo
│   └── test_agent.py         # Full test suite (20 scenarios)
├── tests/
│   ├── conftest.py           # Test fixtures + mock setup
│   └── test_agent_integration.py  # Integration tests
├── data/                     # Dataset (CSVs + PDFs)
│   ├── scada_timeseries.csv  # 207K rows, 90 days, 8 stations
│   ├── pipeline_segment_metadata.csv
│   ├── labeled_leak_events.csv (5 events)
│   ├── labeled_false_positive_events.csv (15 events)
│   ├── valve_status.csv, gas_composition.csv, weather_conditions.csv
│   └── reference_docs/
│       ├── pipeline_operating_procedures.pdf
│       └── dot_phmsa_regulatory_reference.pdf
├── README.md                 # This file
├── DEPLOYMENT_GUIDE.md       # Detailed deployment steps
└── pyproject.toml            # Python project config + pytest settings
```

---

## Configuration Reference

### Environment Variables (Agent Runtime)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GATEWAY_URL` | Yes | (empty) | AgentCore Gateway MCP endpoint |
| `AGENTCORE_MEMORY_ID` | No | (empty) | Memory resource for session persistence |
| `MODEL_ID` | No | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model |
| `AWS_DEFAULT_REGION` | No | `us-west-2` | AWS region |

### Environment Variables (Dashboard)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCADA_BUCKET` | No | `pipeline-integrity-agent-data-<ACCOUNT>-dev` | S3 bucket |
| `INCIDENTS_TABLE` | No | `pipeline-integrity-agent-Incidents-dev` | DynamoDB table |
| `SEGMENTS_TABLE` | No | `pipeline-integrity-agent-PipelineSegments-dev` | DynamoDB table |
| `VALVE_TABLE` | No | `pipeline-integrity-agent-ValveStatus-dev` | DynamoDB table |

### Agent Tools

| Tool | Source | Purpose |
|------|--------|---------|
| `query_scada_readings` | Gateway → Lambda | Fetch SCADA telemetry by station/time |
| `check_compressor_events` | Gateway → Lambda | Detect compressor transients |
| `check_valve_changes` | Gateway → Lambda | Detect valve position changes |
| `query_station_metadata` | Gateway → Lambda | Get segment geometry/valves |
| `create_incident` | Gateway → Lambda | Write incident to DynamoDB |
| `send_alert` | Gateway → Lambda | Publish to SNS topic |
| `calculate_mass_balance` | Custom @tool | Generate Code Interpreter code |
| `estimate_leak_location` | Custom @tool | Pressure gradient localization |
| `calculate_line_pack_correction` | Custom @tool | Temperature correction |
| `estimate_leak_rate` | Custom @tool | Leak rate from deficit |
| `classify_severity` | Custom @tool | Seep/moderate/significant/near-rupture |
| `get_operational_baseline` | Custom @tool | Retrieve baselines from LTM |
| `store_event_signature` | Custom @tool | Store patterns for future disambiguation |
| `code_interpreter` | AgentCore | Execute Python physics calculations |

---

## Troubleshooting

### Agent returns 500 error

```bash
aws logs tail "/aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT" --since 5m --region us-west-2
```

| Error | Cause | Fix |
|-------|-------|-----|
| `ValidationException: model identifier is invalid` | Model not enabled | Enable model in Bedrock console |
| `ThrottlingException: Too many tokens` | Rate limit hit | Wait 1-2 min, or switch to Haiku |
| `403 Forbidden` on Gateway URL | Missing IAM permission | Add `InvokeGateway` to agent role |
| `TypeError: JSONSerializableDict.get()` | SDK compatibility | Use `.get("key") or "default"` |
| `ResourceNotFoundException: Legacy model` | Model deprecated | Use active model ID |

### Gateway target returns errors

```bash
aws logs tail "/aws/lambda/pipeline-integrity-agent-scada-query-dev" --since 5m --region us-west-2
```

The Gateway sends tool arguments directly as the Lambda event (no `tool_name` wrapper). The Lambda infers the tool from the argument structure.

### Knowledge Base returns 0 results

- Verify PDFs uploaded: `aws s3 ls s3://<bucket>/knowledge-base/`
- Re-run ingestion: `python3 scripts/create_knowledge_base.py`
- Check data access policy includes the KB role ARN

### Dashboard not showing live data

- Ensure `SCADA_BUCKET` env var is set (or default is correct in utils.py)
- Run `simulate_live_scada.py` in a separate terminal
- Verify: `aws s3 ls s3://<bucket>/scada/live_readings.csv`
- SageMaker role needs `s3:PutObject` for the simulation script

---

## Cleanup

```bash
# 1. Destroy AgentCore resources (agent + memory)
export AGENTCORE_SUPPRESS_RECOMMENDATION=1
agentcore destroy

# 2. Delete Gateway
python3 -c "
import boto3
client = boto3.client('bedrock-agentcore-control', region_name='us-west-2')
gateways = client.list_gateways()
for gw in gateways.get('items', []):
    targets = client.list_gateway_targets(gatewayIdentifier=gw['gatewayId'])
    for t in targets.get('items', []):
        client.delete_gateway_target(gatewayIdentifier=gw['gatewayId'], targetId=t['targetId'])
    client.delete_gateway(gatewayIdentifier=gw['gatewayId'])
    print(f'Deleted gateway: {gw[\"gatewayId\"]}')
"

# 3. Delete Knowledge Base
python3 -c "
import boto3
bedrock = boto3.client('bedrock-agent', region_name='us-west-2')
kbs = bedrock.list_knowledge_bases()
for kb in kbs.get('knowledgeBaseSummaries', []):
    if 'pipeline' in kb['name']:
        dss = bedrock.list_data_sources(knowledgeBaseId=kb['knowledgeBaseId'])
        for ds in dss.get('dataSourceSummaries', []):
            bedrock.delete_data_source(knowledgeBaseId=kb['knowledgeBaseId'], dataSourceId=ds['dataSourceId'])
        bedrock.delete_knowledge_base(knowledgeBaseId=kb['knowledgeBaseId'])
        print(f'Deleted KB: {kb[\"knowledgeBaseId\"]}')
"

# 4. Delete OpenSearch Serverless collection
python3 -c "
import boto3
aoss = boto3.client('opensearchserverless', region_name='us-west-2')
colls = aoss.list_collections(collectionFilters={'name': 'pia-kb-collection'})
for c in colls.get('collectionSummaries', []):
    aoss.delete_collection(id=c['id'])
    print(f'Deleted collection: {c[\"id\"]}')
# Delete policies
for name in ['pia-kb-enc', 'pia-kb-net']:
    try: aoss.delete_security_policy(name=name, type='encryption' if 'enc' in name else 'network')
    except: pass
try: aoss.delete_access_policy(name='pia-kb-access', type='data')
except: pass
"

# 5. Delete CloudFormation stack
aws cloudformation delete-stack --stack-name pipeline-integrity-agent --region us-west-2

# 6. Delete artifacts bucket
aws s3 rb s3://pipeline-integrity-agent-artifacts-${ACCOUNT_ID} --force

# 7. Delete SageMaker Studio (if created)
# aws sagemaker delete-space --domain-id <id> --space-name pipeline-dashboard
# aws sagemaker delete-user-profile --domain-id <id> --user-profile-name pipeline-controller
# aws sagemaker delete-domain --domain-id <id>
```

---

## Cost Estimate

| Service | Cost (Demo Usage) | Notes |
|---------|-------------------|-------|
| Bedrock Claude Sonnet 4 | ~$0.05/investigation | Input + output tokens |
| AgentCore Runtime | ~$0.01/invocation | Serverless, pay-per-use |
| AgentCore Code Interpreter | ~$0.01/session | Per calculation |
| OpenSearch Serverless | **~$0.50/hour** | Most expensive — delete when not demoing |
| Lambda | < $0.01/month | Free tier covers demo usage |
| DynamoDB | < $0.01/month | On-demand, minimal reads |
| S3 | < $0.01/month | ~25 MB stored |
| SageMaker Studio | ~$0.05/hour | ml.t3.medium instance |
| SNS | Free | < 1000 notifications |

**Important:** The OpenSearch Serverless collection costs ~$0.50/hour even when idle. Delete it when not actively demoing to avoid charges.

---

## Key Design Decisions

1. **Why AgentCore Gateway with AWS_IAM auth (not Cognito)?**
   The agent runs inside AgentCore Runtime which has IAM credentials. AWS_IAM auth lets the agent call the Gateway directly with SigV4 signing — no OAuth token management needed.

2. **Why separate Knowledge Base from CloudFormation?**
   CloudFormation creates the OpenSearch collection, but the vector index must be created via API after the collection is ACTIVE. CloudFormation can't orchestrate this ordering, so we use a Python script.

3. **Why Code Interpreter for physics calculations?**
   The agent generates Python code for mass balance, pressure gradient, and line pack calculations, then executes it in a sandboxed environment. This ensures reproducible, auditable calculations rather than LLM approximations.

4. **Why Strands SDK (not LangChain/CrewAI)?**
   Strands is purpose-built for Bedrock AgentCore with native support for the Runtime, Memory, Code Interpreter, and Gateway integrations. The `@tool` decorator pattern is clean and the SDK handles the agent loop natively.

5. **Why Claude Sonnet 4 (not Haiku)?**
   Sonnet follows complex multi-step instructions more reliably and uses fewer tool calls (9-12 vs 20+ for Haiku). This results in faster completion and no looping behavior.

---

## References

- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [Strands Agents SDK](https://strandsagents.com/)
- [AgentCore Starter Toolkit](https://github.com/aws/bedrock-agentcore-starter-toolkit)
- [DOT PHMSA Pipeline Safety Regulations (49 CFR 191)](https://www.ecfr.gov/current/title-49/subtitle-B/chapter-I/subchapter-D/part-191)

## Demo
https://www.youtube.com/watch?v=FRqtX8cU46g

End
