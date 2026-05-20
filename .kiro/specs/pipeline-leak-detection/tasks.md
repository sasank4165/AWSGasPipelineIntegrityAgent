# Implementation Plan

- [x] 1. Set up project structure and core data models
  - Create the directory structure: `infrastructure/`, `lambdas/scada_query/`, `lambdas/incident_mgmt/`, `agent/`, `scripts/`, `data/`
  - Copy dataset files from `/home/ubuntu/Downloads/use-case-3-data/data/` into the project `data/` directory
  - Create `agent/models.py` with Python dataclasses for `AnomalyEvent`, `ScadaReading`, `PipelineSegment`, `IncidentReport`, `StationBaseline`
  - Create `agent/requirements.txt` with `strands-agents`, `bedrock-agentcore`, `strands-agents-tools`, `boto3`
  - _Requirements: 1.1, 3.3, 4.1, 9.1_

- [x] 2. Create CloudFormation infrastructure template
- [x] 2.1 Define S3 bucket, DynamoDB tables, and IAM roles
  - Create `infrastructure/template.yaml` with S3 bucket for SCADA data and KB documents
  - Add DynamoDB tables: `PipelineSegments` (partition key: segment_id), `ValveStatus` (partition key: valve_id), `Incidents` (partition key: incident_id)
  - Define IAM execution role for AgentCore Runtime with permissions for Bedrock, S3, DynamoDB, Lambda, SNS, Code Interpreter
  - Define Lambda execution roles with S3 read and DynamoDB access
  - _Requirements: 9.1, 9.2, 9.5_

- [x] 2.2 Define Lambda functions and SNS topic
  - Add Lambda function resources for `scada-query` and `incident-mgmt` with Python 3.11 runtime
  - Add SNS topic for control room alerts
  - Add Lambda permission for AgentCore Gateway invocation
  - _Requirements: 5.4, 9.2, 9.5_

- [x] 2.3 Define Bedrock Knowledge Base with S3 data source
  - Add Knowledge Base resource with Amazon Titan Embeddings v2 model
  - Add S3 data source connector pointing to `knowledge-base/` prefix in the S3 bucket
  - Add IAM role for Knowledge Base with S3 read and Bedrock model access
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 2.4 Write unit tests for CloudFormation template validation
  - Validate template syntax with `aws cloudformation validate-template`
  - _Requirements: 9.1_

- [x] 3. Implement Lambda tools
- [x] 3.1 Implement SCADA query Lambda
  - Create `lambdas/scada_query/handler.py` with functions: `query_scada_readings` (filter by station, time range), `check_compressor_events` (filter compressor_start events in time window), `check_valve_changes` (filter valve position changes), `query_station_metadata` (return segment info from DynamoDB)
  - Lambda reads SCADA CSV from S3 using pandas, filters by parameters, returns JSON
  - Include type hints and educational inline comments
  - _Requirements: 1.1, 2.1, 2.2, 3.1, 9.2_

- [x] 3.2 Implement incident management Lambda
  - Create `lambdas/incident_mgmt/handler.py` with functions: `create_incident` (write to DynamoDB Incidents table with unique ID), `send_alert` (publish to SNS topic with structured message)
  - Include incident ID generation (format: INC-YYYY-NNNN)
  - _Requirements: 5.4, 5.5_

- [x] 3.3 Write unit tests for Lambda handlers
  - Test SCADA query with sample CSV data and various filter combinations
  - Test incident creation with mock DynamoDB
  - _Requirements: 2.1, 5.5_

- [x] 4. Implement agent system prompt and tools
- [x] 4.1 Create the agent system prompt
  - Create `agent/prompts.py` with `PIPELINE_INTEGRITY_SYSTEM_PROMPT` encoding the full reasoning workflow: anomaly analysis → false positive check → leak localization → severity assessment → incident response
  - Include instructions for the agent to use Code Interpreter for calculations, check compressor/valve/weather before declaring a leak, and format output as structured incident report
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.1, 4.2, 5.1_

- [x] 4.2 Implement custom @tool functions for Code Interpreter calculations
  - Create `agent/tools.py` with Strands `@tool` decorated functions:
    - `calculate_mass_balance`: Takes station readings, gas composition, returns deficit corrected for temperature and compressibility
    - `estimate_leak_location`: Takes pressure readings at bounding stations + segment metadata, returns mile marker range with confidence interval
    - `calculate_line_pack_correction`: Takes temperature delta + segment specs + gas composition, returns expected line pack change in MMSCF
    - `estimate_leak_rate`: Takes mass balance deficit + gas composition, returns leak rate in MMSCFD
    - `classify_severity`: Takes leak rate, returns severity category (seep/moderate/significant/near_rupture)
  - Each tool prepares Python code strings and invokes Code Interpreter for execution
  - _Requirements: 3.2, 3.3, 4.1, 4.2, 4.3, 9.3_

- [x] 4.3 Implement memory integration tools
  - Add `@tool` functions for memory operations:
    - `get_operational_baseline`: Retrieve per-station baselines from AgentCore LTM
    - `store_event_signature`: Store confirmed false positive or leak signature in LTM for future disambiguation
  - Use `bedrock_agentcore.memory.MemoryClient` for memory operations
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 5. Implement main agent entrypoint
- [x] 5.1 Create the Strands agent with AgentCore Runtime wrapper
  - Create `agent/agent.py` with `BedrockAgentCoreApp`, `Agent` initialization, memory hooks, Code Interpreter tool, and Gateway MCP tool connection
  - Wire up all custom tools from `tools.py`
  - Implement `@app.entrypoint` that parses the anomaly event payload and invokes the agent
  - Use `AgentCoreMemoryConfig` and `AgentCoreMemorySessionManager` for session memory
  - Use `AgentCoreCodeInterpreter` from `strands_tools.code_interpreter`
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 6.4_

- [x] 5.2 Implement Gateway MCP tool connection
  - Connect to AgentCore Gateway URL to discover and use Lambda-backed MCP tools (SCADA query, incident mgmt, KB query)
  - Use MCP client session with OAuth token management
  - _Requirements: 9.2, 9.5, 9.6_

- [x] 6. Create deployment and data upload scripts
- [x] 6.1 Create data upload script
  - Create `scripts/upload_data.py` that uploads all CSV files to S3 bucket under appropriate prefixes and PDFs to `knowledge-base/` prefix
  - Populate DynamoDB tables (PipelineSegments, ValveStatus) from CSV data
  - _Requirements: 1.1, 7.1_

- [x] 6.2 Create Knowledge Base sync script
  - Create `scripts/sync_knowledge_base.py` that triggers a data source sync on the Bedrock Knowledge Base after PDFs are uploaded
  - Wait for sync completion and report status
  - _Requirements: 7.1, 7.2_

- [x] 6.3 Create full deployment script
  - Create `scripts/deploy.sh` that orchestrates: CloudFormation deploy → data upload → KB sync → agentcore configure → agentcore deploy
  - Include error handling and status reporting at each step
  - _Requirements: 9.1_

- [x] 7. Create test and validation scripts
- [x] 7.1 Create agent test script with labeled scenarios
  - Create `scripts/test_agent.py` that invokes the deployed agent with payloads simulating each of the 5 labeled leak events and 15 false positive events
  - Parse agent responses and compare against expected classifications
  - Report accuracy metrics (detection rate, false positive rate, localization accuracy)
  - _Requirements: 2.4, 2.5, 3.1, 3.2, 4.1, 4.2_

- [x] 7.2 Create single-scenario demo invocation script
  - Create `scripts/demo_invoke.py` that invokes the agent with the example scenario from the use case (Station 5 pressure drops 12 PSI in 8 minutes)
  - Print the full incident report output for demo purposes
  - _Requirements: 5.1, 5.2, 5.3_

- [x] 7.3 Write integration tests for end-to-end agent flow
  - Test agent invocation with a real leak scenario payload and verify tool call sequence
  - Test agent invocation with a false positive scenario and verify dismissal
  - _Requirements: 2.4, 2.5, 5.1_

- [x] 8. Implement monitoring dashboard (Streamlit on SageMaker Studio)
- [x] 8.1 Create dashboard data utilities and project structure
  - Create `dashboard/requirements.txt` with streamlit, boto3, pandas, plotly
  - Create `dashboard/utils.py` with helper functions: `get_latest_scada_readings` (read latest rows from S3 CSV), `get_incidents` (scan DynamoDB Incidents table), `get_pipeline_segments` (scan DynamoDB Segments table), `get_valve_status` (scan DynamoDB ValveStatus table)
  - All helpers use boto3 directly with the SageMaker Studio execution role credentials
  - _Requirements: 8.5, 8.6_

- [x] 8.2 Implement pipeline overview page
  - Create `dashboard/app.py` as the Streamlit multi-page app entry point with sidebar navigation and auto-refresh toggle (30s interval)
  - Create `dashboard/pages/1_pipeline_overview.py` showing: 8-station status cards with pressure/flow/temp gauges, segment health color coding (green/yellow/red based on latest mass_balance_deficit), and a summary of active incident count
  - Use Plotly gauge charts for station metrics
  - _Requirements: 8.1, 8.4_

- [x] 8.3 Implement active incidents and incident detail pages
  - Create `dashboard/pages/2_active_incidents.py` with a sortable table of all incidents from DynamoDB, color-coded severity badges, timestamps, and affected segments
  - Create `dashboard/pages/3_incident_detail.py` that displays the full agent reasoning timeline for a selected incident: anomaly trigger values, false positive checks performed, localization results, severity assessment, and recommended actions
  - _Requirements: 8.2, 8.3_

- [x] 8.4 Implement historical trends page
  - Create `dashboard/pages/4_historical_trends.py` with time-series line charts (Plotly) for pressure and flow at user-selected stations over a configurable time window
  - Include station selector dropdown and time range picker
  - _Requirements: 8.1_
