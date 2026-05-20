"""Shared test configuration for integration tests.

Sets environment variables and mocks external dependencies that are not
installed in the test environment (AgentCore SDK, Strands, MCP proxy).
"""

import os
import sys
from unittest.mock import MagicMock

# Set environment variables before any agent module imports
os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["GATEWAY_URL"] = ""  # Disable Gateway for integration tests
os.environ["AGENTCORE_MEMORY_ID"] = ""  # Disable Memory for integration tests
os.environ["MODEL_ID"] = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"
os.environ["SCADA_BUCKET"] = "test-bucket"
os.environ["SEGMENTS_TABLE"] = "test-segments-table"
os.environ["VALVE_TABLE"] = "test-valve-table"
os.environ["INCIDENTS_TABLE"] = "test-incidents-table"
os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-west-2:123456789012:test-topic"

# --- Mock external dependencies not installed in the test environment ---


# Mock BedrockAgentCoreApp so @app.entrypoint passes through the function
class MockBedrockAgentCoreApp:
    """Mock that makes @app.entrypoint a pass-through decorator."""

    def entrypoint(self, fn):
        """Pass-through decorator — returns the original function unchanged."""
        return fn

    def run(self):
        pass


# Mock bedrock_agentcore
mock_bedrock_agentcore = MagicMock()
mock_bedrock_agentcore.runtime.BedrockAgentCoreApp = MockBedrockAgentCoreApp

# Mock MemoryClient to return empty results (simulating no memory configured)
mock_memory_client_instance = MagicMock()
mock_memory_client_instance.get_last_k_turns.return_value = []
mock_memory_client_instance.retrieve_memories.return_value = []
mock_memory_client_instance.create_event.return_value = {"eventId": "mock-event-id"}

mock_memory_client_class = MagicMock(return_value=mock_memory_client_instance)
mock_bedrock_agentcore.memory.MemoryClient = mock_memory_client_class

sys.modules["bedrock_agentcore"] = mock_bedrock_agentcore
sys.modules["bedrock_agentcore.runtime"] = mock_bedrock_agentcore.runtime
sys.modules["bedrock_agentcore.memory"] = mock_bedrock_agentcore.memory

# Mock mcp_proxy_for_aws
mock_mcp_proxy = MagicMock()
sys.modules["mcp_proxy_for_aws"] = mock_mcp_proxy
sys.modules["mcp_proxy_for_aws.client"] = mock_mcp_proxy.client

# Mock strands — Agent is a MagicMock class, @tool is a pass-through
mock_strands = MagicMock()
mock_strands.tool = lambda fn: fn  # @tool decorator passes through
sys.modules["strands"] = mock_strands
sys.modules["strands.hooks"] = mock_strands.hooks
sys.modules["strands.tools"] = MagicMock()
sys.modules["strands.tools.mcp"] = MagicMock()

# Mock strands_tools
mock_strands_tools = MagicMock()
sys.modules["strands_tools"] = mock_strands_tools
sys.modules["strands_tools.code_interpreter"] = mock_strands_tools.code_interpreter
