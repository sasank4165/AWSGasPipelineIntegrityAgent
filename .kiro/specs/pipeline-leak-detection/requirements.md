# Requirements Document

## Introduction

This feature implements an autonomous Pipeline Integrity Agent using Amazon Bedrock AgentCore that monitors SCADA telemetry from 8 stations across a 200-mile natural gas transmission pipeline. The agent detects leaks by reasoning about pressure drops and flow imbalances in full operational context — distinguishing real leaks from false positives caused by compressor starts, valve changes, and temperature-driven line pack shifts. When a real anomaly is confirmed, the agent localizes the leak segment, assesses severity, checks regulatory thresholds, and orchestrates the incident response workflow including draft PHMSA notifications.

The system replaces brittle threshold-based SCADA alarms with contextual AI reasoning, targeting 98% detection accuracy, sub-5-minute response times, and near-zero false positive escalations.

## Requirements

### Requirement 1: Real-Time Telemetry Ingestion and Anomaly Triggering

**User Story:** As a pipeline controller, I want SCADA telemetry to be continuously ingested and anomalies automatically flagged, so that potential leak events are detected within seconds of onset.

#### Acceptance Criteria

1. WHEN a SCADA reading arrives from any of the 8 stations THEN the system SHALL ingest and store the reading with all fields (pressure, flow, temperature, compressor status, valve position, line pack, mass balance deficit) within 30 seconds.
2. WHEN the mass balance deficit between adjacent stations exceeds a configurable threshold (default: 0.3 MMSCFD) THEN the system SHALL trigger an EventBridge event to invoke the Pipeline Integrity Agent.
3. WHEN a pressure drop rate exceeds a configurable threshold (default: 1.5 PSI/minute sustained over 5 minutes) THEN the system SHALL trigger an EventBridge event to invoke the Pipeline Integrity Agent.
4. IF multiple anomaly triggers fire within a 10-minute window for the same segment THEN the system SHALL consolidate them into a single agent invocation to avoid duplicate investigations.

### Requirement 2: False Positive Disambiguation

**User Story:** As a pipeline controller, I want the agent to automatically rule out known operational transients before escalating an alert, so that I am not overwhelmed by false alarms that cause unnecessary shutdowns.

#### Acceptance Criteria

1. WHEN the agent is invoked for an anomaly THEN it SHALL check compressor event logs for the affected stations within the preceding 2 hours and compare the pressure signature against historical compressor-start patterns.
2. WHEN the agent is invoked for an anomaly THEN it SHALL check valve position change logs for the affected stations within the preceding 30 minutes.
3. WHEN the agent is invoked for an anomaly THEN it SHALL fetch current weather/temperature data and calculate the expected line pack contraction or expansion due to ambient temperature changes.
4. IF the anomaly signature matches a known false positive pattern (compressor start, valve change, or temperature-driven line pack shift) AND the residual unexplained deficit after correction is below 0.2 MMSCFD THEN the system SHALL classify the event as a false positive and log it without escalating.
5. IF the anomaly cannot be explained by operational transients THEN the system SHALL proceed to leak localization and severity assessment.
6. WHEN classifying an event as a false positive THEN the agent SHALL record the reasoning chain (which checks were performed, what values were found, why the event was dismissed) for audit purposes.

### Requirement 3: Leak Localization

**User Story:** As a pipeline controller, I want the agent to estimate the physical location of a confirmed leak, so that inspection crews can be dispatched to the correct segment without searching the entire pipeline.

#### Acceptance Criteria

1. WHEN a real anomaly is confirmed THEN the agent SHALL identify the affected pipeline segment (from-station to to-station) based on where the mass balance deficit is observed.
2. WHEN a real anomaly is confirmed THEN the agent SHALL estimate the leak location as a mile marker range using pressure gradient analysis between the bounding stations.
3. WHEN localizing a leak THEN the agent SHALL use pipeline segment metadata (length, diameter, elevation profile) and gas composition (compressibility factor) in its calculations via the Code Interpreter.
4. WHEN reporting the estimated location THEN the agent SHALL include a confidence interval (e.g., +/- miles) based on the quality of available data.

### Requirement 4: Severity Assessment and Leak Rate Estimation

**User Story:** As a pipeline controller, I want the agent to classify leak severity and estimate the release rate, so that I can prioritize response actions appropriately.

#### Acceptance Criteria

1. WHEN a leak is confirmed THEN the agent SHALL estimate the leak rate in MMSCFD using mass balance calculations corrected for temperature and gas composition.
2. WHEN a leak rate is estimated THEN the agent SHALL classify severity as one of: seep (< 0.25 MMSCFD), moderate (0.25–0.75 MMSCFD), significant (0.75–1.5 MMSCFD), or near-rupture (> 1.5 MMSCFD).
3. WHEN severity is assessed THEN the agent SHALL check the estimated gas loss against DOT PHMSA reporting thresholds (49 CFR 191.5) to determine if immediate notification is required.
4. WHEN the estimated release exceeds PHMSA thresholds THEN the agent SHALL flag the incident as requiring mandatory NRC notification within 1 hour.

### Requirement 5: Incident Response Orchestration

**User Story:** As a pipeline controller, I want the agent to generate a complete incident response package with recommended actions, so that I can act immediately without manually assembling information from multiple systems.

#### Acceptance Criteria

1. WHEN a leak is confirmed THEN the agent SHALL generate a structured incident report containing: anomaly analysis, false positive check results, leak localization, severity assessment, and recommended actions.
2. WHEN generating recommended actions THEN the agent SHALL identify the specific isolation valves to close (by valve ID and mile marker) based on the leak location and pipeline segment metadata.
3. WHEN the incident requires PHMSA notification THEN the agent SHALL draft a regulatory notification pre-populated with all required fields from PHMSA Form 7100.1 (operator info, pipeline system info, incident details, consequences).
4. WHEN the incident report is complete THEN the agent SHALL deliver it to the control room via SNS notification within 5 minutes of the initial anomaly trigger.
5. WHEN an incident is created THEN the agent SHALL log it to the incident database (DynamoDB) with a unique incident ID, timestamp, all assessment details, and status tracking.

### Requirement 6: Operational Baseline and Memory

**User Story:** As a pipeline controller, I want the agent to learn what "normal" looks like for each station over time, so that its anomaly detection improves and adapts to seasonal and operational changes.

#### Acceptance Criteria

1. WHEN the agent processes telemetry THEN it SHALL maintain per-station operating baselines (normal pressure range, normal flow range, typical line pack) in AgentCore long-term memory.
2. WHEN comparing current readings against baselines THEN the agent SHALL use station-specific historical norms rather than fixed global thresholds.
3. WHEN a false positive is confirmed THEN the agent SHALL store the event signature in long-term memory to improve future disambiguation accuracy.
4. WHEN an incident investigation is in progress THEN the agent SHALL use AgentCore short-term memory to maintain full session context (all readings checked, calculations performed, decisions made) throughout the investigation.
5. IF the pipeline's operating envelope changes (e.g., seasonal throughput adjustments) THEN the system SHALL update baselines within 7 days of the new steady-state being established.

### Requirement 7: Knowledge Base Integration

**User Story:** As a pipeline controller, I want the agent to reference operating procedures and regulatory requirements during its analysis, so that its recommendations are always compliant and operationally sound.

#### Acceptance Criteria

1. WHEN the agent performs leak analysis THEN it SHALL have access to indexed pipeline operating procedures, including normal operating envelopes, isolation procedures, and emergency shutdown steps.
2. WHEN the agent assesses regulatory obligations THEN it SHALL reference the indexed DOT PHMSA regulatory requirements (49 CFR Part 191) to determine reporting thresholds and timelines.
3. WHEN the agent generates isolation valve recommendations THEN it SHALL cross-reference the operating procedures for correct valve closure sequences.
4. WHEN the agent drafts PHMSA notifications THEN it SHALL use the indexed Form 7100.1 field requirements to ensure completeness.

### Requirement 8: Agent Infrastructure and Deployment

**User Story:** As a platform engineer, I want the pipeline integrity agent deployed on AgentCore with proper tool integrations, so that it can be invoked reliably and scale with telemetry volume.

#### Acceptance Criteria

1. WHEN the agent is deployed THEN it SHALL be hosted on AgentCore Runtime with EventBridge trigger integration for automatic invocation on anomaly detection.
2. WHEN the agent needs to query SCADA data THEN it SHALL call the SCADA query Lambda tool exposed via AgentCore Gateway as an MCP tool.
3. WHEN the agent needs to perform calculations (mass balance, pressure transient analysis, line pack estimation, leak rate) THEN it SHALL use AgentCore Code Interpreter for sandboxed Python execution.
4. WHEN the agent needs real-time weather data THEN it SHALL use AgentCore Browser to fetch current conditions for temperature correction.
5. WHEN the agent needs to create incidents or control valves THEN it SHALL call the incident management and valve control Lambda tools exposed via AgentCore Gateway.
6. WHEN the agent needs pipeline specs or regulatory references THEN it SHALL query the Bedrock Knowledge Base exposed as an MCP tool via AgentCore Gateway.
