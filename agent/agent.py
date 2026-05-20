"""Main entrypoint for the Pipeline Integrity Agent.

Deploys on Amazon Bedrock AgentCore Runtime using the Strands Agents SDK.
Connects to AgentCore Gateway for Lambda-backed MCP tools (SCADA query,
incident management, Knowledge Base), uses AgentCore Code Interpreter for
physics calculations, and AgentCore Memory for operational baselines.

Usage:
    Local testing:  python agent.py
    Deploy:         agentcore configure -e agent/agent.py && agentcore deploy
    Invoke:         agentcore invoke '{"event_id": "...", ...}'
"""

import json
import logging
import os
import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.hooks import AgentInitializedEvent, HookProvider, MessageAddedEvent
from strands.tools.mcp import MCPClient

# Conditional imports — these may not be available in all environments
try:
    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
except ImportError:
    aws_iam_streamablehttp_client = None

try:
    from strands_tools.code_interpreter import AgentCoreCodeInterpreter
except ImportError:
    AgentCoreCodeInterpreter = None

from prompts import PIPELINE_INTEGRITY_SYSTEM_PROMPT
from tools import (
    calculate_line_pack_correction,
    calculate_mass_balance,
    classify_severity,
    estimate_leak_location,
    estimate_leak_rate,
    get_operational_baseline,
    store_event_signature,
)

# --- Configuration from environment variables ---
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Initialize AgentCore Runtime app ---
app = BedrockAgentCoreApp()

# --- Initialize Code Interpreter tool (lazy — created on first use) ---
_code_interpreter_tool = None


def _get_code_interpreter():
    """Lazily initialize Code Interpreter to avoid startup failures."""
    global _code_interpreter_tool
    if _code_interpreter_tool is None and AgentCoreCodeInterpreter is not None:
        try:
            _code_interpreter_tool = AgentCoreCodeInterpreter(region=AWS_REGION)
        except Exception as e:
            logger.warning("Failed to initialize Code Interpreter: %s", e)
    return _code_interpreter_tool


# --- Memory client for session persistence ---
memory_client = None
if MEMORY_ID:
    try:
        memory_client = MemoryClient(region_name=AWS_REGION)
    except Exception as e:
        logger.warning("Failed to initialize MemoryClient: %s", e)


class PipelineMemoryHook(HookProvider):
    """Hook that persists agent conversation to AgentCore Memory.

    Loads recent investigation context on agent start (short-term memory)
    and saves each message for audit trail and session continuity.
    """

    def on_agent_initialized(self, event: AgentInitializedEvent) -> None:
        """Load recent conversation history from memory when agent starts."""
        if not MEMORY_ID or not memory_client:
            return

        session_id = event.agent.state.get("session_id") or "default"
        try:
            # Retrieve last few turns to maintain investigation context
            turns = memory_client.get_last_k_turns(
                memory_id=MEMORY_ID,
                actor_id="pipeline-integrity-agent",
                session_id=session_id,
                k=5,
            )
            if turns:
                context = "\n".join(
                    f"{m['role']}: {m['content']['text']}" for t in turns for m in t
                )
                event.agent.system_prompt += (
                    f"\n\n## Previous Investigation Context\n{context}"
                )
        except Exception as e:
            # Memory unavailable — continue without history (error handling per design)
            logger.warning("Failed to load memory context: %s", e)

    def on_message_added(self, event: MessageAddedEvent) -> None:
        """Save each message to memory for session persistence and audit."""
        if not MEMORY_ID or not memory_client:
            return

        session_id = event.agent.state.get("session_id") or "default"
        try:
            msg = event.agent.messages[-1]
            content = str(msg.get("content", ""))
            role = msg.get("role", "assistant")
            memory_client.create_event(
                memory_id=MEMORY_ID,
                actor_id="pipeline-integrity-agent",
                session_id=session_id,
                messages=[(content, role)],
            )
        except Exception as e:
            # Non-fatal — agent continues even if memory write fails
            logger.warning("Failed to save message to memory: %s", e)

    def register_hooks(self, registry) -> None:
        """Register memory hooks with the agent lifecycle."""
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        registry.add_callback(MessageAddedEvent, self.on_message_added)


def _create_gateway_mcp_client() -> MCPClient | None:
    """Create an MCP client connected to AgentCore Gateway.

    The Gateway exposes Lambda-backed tools (SCADA query, incident management,
    Knowledge Base) as MCP endpoints with IAM authorization.
    Returns None if GATEWAY_URL is not configured or mcp_proxy_for_aws is unavailable.
    """
    if not GATEWAY_URL:
        logger.warning("GATEWAY_URL not set — Gateway MCP tools will be unavailable.")
        return None

    if aws_iam_streamablehttp_client is None:
        logger.warning("mcp_proxy_for_aws not available — Gateway MCP tools will be unavailable.")
        return None

    # Use mcp-proxy-for-aws for SigV4-signed requests to AgentCore Gateway
    mcp_client = MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=GATEWAY_URL,
            aws_region=AWS_REGION,
            aws_service="bedrock-agentcore",
        )
    )
    return mcp_client


def _get_custom_tools() -> list:
    """Build the list of custom tools, including Code Interpreter if available."""
    tools = [
        calculate_mass_balance,
        estimate_leak_location,
        calculate_line_pack_correction,
        estimate_leak_rate,
        classify_severity,
        get_operational_baseline,
        store_event_signature,
    ]
    ci = _get_code_interpreter()
    if ci is not None:
        tools.append(ci.code_interpreter)
    return tools


@app.entrypoint
def invoke(payload: dict, context) -> str:
    """Main entrypoint triggered by anomaly events or direct invocation.

    Parses the anomaly event payload, initializes the agent with all tools
    (custom + Gateway MCP + Code Interpreter), and runs the full investigation
    workflow defined in the system prompt.

    Args:
        payload: Anomaly event dict with keys: event_id, timestamp, anomaly_type,
                 affected_stations, affected_segment, trigger_values, severity.
                 Or a simple {"prompt": "..."} for direct testing.
        context: RequestContext from AgentCore Runtime with session_id.

    Returns:
        JSON string of the incident report or analysis result.
    """
    start_time = time.time()

    # Extract session ID from runtime context for memory isolation
    session_id = "default"
    if hasattr(context, "session_id") and context.session_id:
        session_id = context.session_id

    # Build the prompt from the anomaly event payload
    if "prompt" in payload:
        # Direct invocation for testing
        user_prompt = payload["prompt"]
    else:
        # Structured anomaly event from EventBridge
        user_prompt = _format_anomaly_prompt(payload)

    # Connect to Gateway MCP tools and run the agent
    gateway_client = _create_gateway_mcp_client()

    custom_tools = _get_custom_tools()

    if gateway_client:
        # Use context manager to maintain MCP connection lifecycle
        with gateway_client:
            gateway_tools = gateway_client.list_tools_sync()
            all_tools = custom_tools + list(gateway_tools)

            agent = Agent(
                model=MODEL_ID,
                system_prompt=PIPELINE_INTEGRITY_SYSTEM_PROMPT,
                tools=all_tools,
                hooks=[PipelineMemoryHook()] if MEMORY_ID else [],
                state={"session_id": session_id},
            )

            response = agent(user_prompt)
    else:
        # No Gateway — run with custom tools only (local testing mode)
        agent = Agent(
            model=MODEL_ID,
            system_prompt=PIPELINE_INTEGRITY_SYSTEM_PROMPT,
            tools=custom_tools,
            hooks=[PipelineMemoryHook()] if MEMORY_ID else [],
            state={"session_id": session_id},
        )

        response = agent(user_prompt)

    # Extract the response text
    elapsed = int(time.time() - start_time)
    result_text = response.message["content"][0]["text"]

    logger.info("Agent completed in %d seconds", elapsed)
    return result_text


def _format_anomaly_prompt(payload: dict) -> str:
    """Format a structured anomaly event payload into a natural language prompt.

    Converts the EventBridge anomaly event into a clear instruction for the agent
    to begin its investigation workflow.
    """
    event_id = payload.get("event_id", "UNKNOWN")
    timestamp = payload.get("timestamp", "UNKNOWN")
    anomaly_type = payload.get("anomaly_type", "UNKNOWN")
    affected_stations = payload.get("affected_stations", [])
    affected_segment = payload.get("affected_segment", "UNKNOWN")
    trigger_values = payload.get("trigger_values", {})
    severity = payload.get("severity", "warning")

    prompt = (
        f"ANOMALY ALERT — Investigate the following event:\n\n"
        f"Event ID: {event_id}\n"
        f"Timestamp: {timestamp}\n"
        f"Anomaly Type: {anomaly_type}\n"
        f"Affected Stations: {', '.join(affected_stations)}\n"
        f"Affected Segment: {affected_segment}\n"
        f"Severity: {severity}\n"
        f"Trigger Values: {json.dumps(trigger_values, indent=2)}\n\n"
        f"Follow your full reasoning workflow: "
        f"anomaly analysis → false positive disambiguation → "
        f"leak localization → severity assessment → incident response. "
        f"Use the Code Interpreter for all physics calculations. "
        f"Query SCADA data, check compressor events, valve changes, and weather. "
        f"Produce a complete structured incident report."
    )
    return prompt


if __name__ == "__main__":
    # Local development: run the agent server on port 8080
    # Test with: curl -X POST http://localhost:8080/invocations -d '{"prompt": "..."}'
    app.run()
