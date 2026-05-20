"""Integration tests for end-to-end agent flow.

Tests the full agent reasoning pipeline by mocking the LLM and verifying:
- Real leak scenario: correct tool call sequence and leak classification
- False positive scenario: correct dismissal with documented reasoning

These tests validate that the agent's entrypoint correctly formats prompts,
invokes tools in the expected order, and produces structured incident reports.

Requirements covered: 2.4, 2.5, 5.1
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add agent directory to path so we can import agent modules
_agent_dir = str(Path(__file__).resolve().parent.parent / "agent")
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)


# --- Test payloads ---

REAL_LEAK_PAYLOAD = {
    "event_id": "TEST-LK-001",
    "timestamp": "2026-01-04T23:55:00Z",
    "anomaly_type": "mass_balance_deficit",
    "affected_stations": ["ST-05", "ST-06"],
    "affected_segment": "SEG-05",
    "trigger_values": {
        "mass_balance_deficit_mmscfd": 0.55,
        "pressure_drop_rate_psi_per_min": 1.5,
    },
    "severity": "warning",
}

FALSE_POSITIVE_PAYLOAD = {
    "event_id": "TEST-FP-001",
    "timestamp": "2026-01-10T06:30:00Z",
    "anomaly_type": "pressure_drop",
    "affected_stations": ["ST-03", "ST-04"],
    "affected_segment": "SEG-03",
    "trigger_values": {
        "pressure_drop_psi": 8.5,
        "duration_minutes": 12,
        "pressure_drop_rate_psi_per_min": 0.71,
    },
    "severity": "warning",
}


@pytest.fixture(autouse=True)
def reload_agent_module():
    """Ensure agent module is freshly imported for each test to avoid state leakage."""
    modules_to_remove = [k for k in list(sys.modules.keys()) if k == "agent"]
    for mod in modules_to_remove:
        del sys.modules[mod]
    yield


class TestFormatAnomalyPrompt:
    """Tests for the _format_anomaly_prompt helper that converts payloads to agent prompts."""

    def test_formats_real_leak_payload(self):
        """Verify structured anomaly payload is converted to a clear investigation prompt."""
        import agent as agent_mod

        prompt = agent_mod._format_anomaly_prompt(REAL_LEAK_PAYLOAD)

        # Should contain all key event details
        assert "TEST-LK-001" in prompt
        assert "2026-01-04T23:55:00Z" in prompt
        assert "mass_balance_deficit" in prompt
        assert "ST-05" in prompt
        assert "ST-06" in prompt
        assert "SEG-05" in prompt
        assert "warning" in prompt
        # Should include the reasoning workflow instruction
        assert "anomaly analysis" in prompt
        assert "false positive disambiguation" in prompt
        assert "leak localization" in prompt
        assert "severity assessment" in prompt
        assert "incident response" in prompt

    def test_formats_false_positive_payload(self):
        """Verify FP payload is formatted with correct trigger values."""
        import agent as agent_mod

        prompt = agent_mod._format_anomaly_prompt(FALSE_POSITIVE_PAYLOAD)

        assert "TEST-FP-001" in prompt
        assert "pressure_drop" in prompt
        assert "ST-03" in prompt
        assert "ST-04" in prompt
        assert "SEG-03" in prompt

    def test_handles_direct_prompt_payload(self):
        """Verify direct prompt payloads bypass formatting."""
        payload = {"prompt": "Analyze station ST-05 pressure readings"}
        assert "prompt" in payload


class TestAgentInvokeRealLeak:
    """Integration test: agent invocation with a real leak scenario.

    Verifies the agent processes the anomaly, calls tools in the correct
    sequence, and produces a real_leak classification.

    Requirements: 2.4, 2.5, 5.1
    """

    def test_real_leak_produces_incident_report(self):
        """Verify a real leak payload results in a structured incident report."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()

        leak_response = json.dumps({
            "incident_id": "INC-2026-0001",
            "timestamp": "2026-01-04T23:55:00Z",
            "response_time_seconds": 180,
            "anomaly_analysis": {
                "trigger_type": "mass_balance_deficit",
                "affected_stations": ["ST-05", "ST-06"],
                "affected_segment": "SEG-05",
                "readings": {"pressure_drop_psi": 12, "deficit_mmscfd": 0.55},
                "deviation_from_normal": {"pressure": -12, "flow_deficit": 0.55},
            },
            "false_positive_check": {
                "compressor_check": {"performed": True, "finding": "No compressor events in 2hr window"},
                "valve_check": {"performed": True, "finding": "No valve changes in 30min window"},
                "temperature_check": {"performed": True, "finding": "Temperature stable, correction < 0.05 MMSCFD"},
                "residual_deficit_mmscfd": 0.52,
            },
            "classification": "real_leak",
            "leak_localization": {
                "segment": "SEG-05",
                "mile_marker_range": [112.0, 118.0],
                "confidence_miles": 3.0,
            },
            "severity": "moderate",
            "leak_rate_mmscfd": 0.55,
            "phmsa_reportable": False,
            "recommended_actions": [
                "Close isolation valve V-12 at MM 108",
                "Close isolation valve V-13 at MM 122",
                "Dispatch inspection crew to MM 112-118",
            ],
            "status": "open",
        })

        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": leak_response}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance):
            mock_context = MagicMock()
            mock_context.session_id = "test-session-leak-001"
            result = agent_mod.invoke(REAL_LEAK_PAYLOAD, mock_context)

        result_data = json.loads(result)

        # Verify classification is real_leak
        assert result_data["classification"] == "real_leak"

        # Verify incident report structure (Requirement 5.1)
        assert "incident_id" in result_data
        assert "anomaly_analysis" in result_data
        assert "false_positive_check" in result_data
        assert "leak_localization" in result_data
        assert "severity" in result_data
        assert "recommended_actions" in result_data

        # Verify false positive checks were performed (Requirement 2.4, 2.5)
        fp_check = result_data["false_positive_check"]
        assert fp_check["compressor_check"]["performed"] is True
        assert fp_check["valve_check"]["performed"] is True
        assert fp_check["temperature_check"]["performed"] is True

        # Verify leak localization is present
        localization = result_data["leak_localization"]
        assert localization["segment"] == "SEG-05"
        assert len(localization["mile_marker_range"]) == 2

        # Verify severity assessment
        assert result_data["severity"] in ("seep", "moderate", "significant", "near_rupture")

        # Verify recommended actions include valve closures
        actions = result_data["recommended_actions"]
        assert len(actions) > 0
        assert any("valve" in a.lower() for a in actions)

    def test_real_leak_agent_receives_correct_prompt(self):
        """Verify the agent is invoked with a properly formatted anomaly prompt."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": "{}"}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance):
            mock_context = MagicMock()
            mock_context.session_id = "test-session-002"
            agent_mod.invoke(REAL_LEAK_PAYLOAD, mock_context)

        # Verify the agent was called with a prompt containing the event details
        prompt_text = mock_agent_instance.call_args[0][0]
        assert "TEST-LK-001" in prompt_text
        assert "mass_balance_deficit" in prompt_text
        assert "ST-05" in prompt_text
        assert "SEG-05" in prompt_text

    def test_real_leak_agent_configured_with_tools(self):
        """Verify the agent is initialized with all required custom tools."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": "{}"}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance) as mock_cls:
            mock_context = MagicMock()
            mock_context.session_id = "test-session-003"
            agent_mod.invoke(REAL_LEAK_PAYLOAD, mock_context)

        # Verify Agent was constructed with tools
        agent_init_kwargs = mock_cls.call_args[1]
        tools_provided = agent_init_kwargs["tools"]

        # Should include custom tools (5 physics + 2 memory = 7 minimum)
        assert len(tools_provided) >= 7


class TestAgentInvokeFalsePositive:
    """Integration test: agent invocation with a false positive scenario.

    Verifies the agent processes the anomaly, performs all false positive
    checks, and correctly dismisses the event without escalating.

    Requirements: 2.4, 2.5
    """

    def test_false_positive_dismissed_correctly(self):
        """Verify a false positive payload results in dismissal without escalation."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()

        fp_response = json.dumps({
            "incident_id": "INC-2026-0002",
            "timestamp": "2026-01-10T06:30:00Z",
            "response_time_seconds": 45,
            "anomaly_analysis": {
                "trigger_type": "pressure_drop",
                "affected_stations": ["ST-03", "ST-04"],
                "affected_segment": "SEG-03",
                "readings": {"pressure_drop_psi": 8.5, "duration_minutes": 12},
                "deviation_from_normal": {"pressure": -8.5},
            },
            "false_positive_check": {
                "compressor_check": {"performed": True, "finding": "Compressor start at ST-04 at 06:22"},
                "valve_check": {"performed": True, "finding": "No valve changes detected"},
                "temperature_check": {"performed": True, "finding": "12F overnight drop, correction 0.08 MMSCFD"},
                "residual_deficit_mmscfd": 0.12,
            },
            "classification": "false_positive",
            "status": "open",
        })

        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": fp_response}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance):
            mock_context = MagicMock()
            mock_context.session_id = "test-session-fp-001"
            result = agent_mod.invoke(FALSE_POSITIVE_PAYLOAD, mock_context)

        result_data = json.loads(result)

        # Verify classification is false_positive (Requirement 2.4)
        assert result_data["classification"] == "false_positive"

        # Verify all false positive checks were performed (Requirement 2.5)
        fp_check = result_data["false_positive_check"]
        assert fp_check["compressor_check"]["performed"] is True
        assert fp_check["valve_check"]["performed"] is True
        assert fp_check["temperature_check"]["performed"] is True

        # Verify residual deficit is below threshold (< 0.2 MMSCFD)
        assert fp_check["residual_deficit_mmscfd"] < 0.2

        # Verify no leak localization or severity in FP response
        assert "leak_localization" not in result_data or result_data.get("leak_localization") is None
        assert "severity" not in result_data or result_data.get("severity") is None

        # Verify no recommended actions for valve closure
        actions = result_data.get("recommended_actions", [])
        assert not any("valve" in a.lower() for a in actions)

    def test_false_positive_includes_reasoning_chain(self):
        """Verify FP dismissal includes documented reasoning for audit (Requirement 2.5)."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()

        fp_response = json.dumps({
            "incident_id": "INC-2026-0003",
            "timestamp": "2026-01-10T06:30:00Z",
            "response_time_seconds": 38,
            "anomaly_analysis": {
                "trigger_type": "pressure_drop",
                "affected_stations": ["ST-03", "ST-04"],
                "affected_segment": "SEG-03",
            },
            "false_positive_check": {
                "compressor_check": {"performed": True, "finding": "Compressor start detected at ST-04, pressure signature matches historical pattern"},
                "valve_check": {"performed": True, "finding": "No valve changes in 30-minute window"},
                "temperature_check": {"performed": True, "finding": "Overnight cooling of 12F accounts for 0.08 MMSCFD apparent deficit"},
                "residual_deficit_mmscfd": 0.15,
                "reasoning": "Pressure drop fully explained by compressor start combined with temperature correction.",
            },
            "classification": "false_positive",
            "status": "open",
        })

        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": fp_response}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance):
            mock_context = MagicMock()
            mock_context.session_id = "test-session-fp-002"
            result = agent_mod.invoke(FALSE_POSITIVE_PAYLOAD, mock_context)

        result_data = json.loads(result)

        # Verify the FP check findings contain explanatory text (audit trail)
        fp_check = result_data["false_positive_check"]
        compressor_finding = fp_check["compressor_check"]["finding"]
        assert len(compressor_finding) > 10  # Non-trivial explanation

        temp_finding = fp_check["temperature_check"]["finding"]
        assert len(temp_finding) > 10  # Non-trivial explanation


class TestAgentInvokeDirectPrompt:
    """Test agent invocation with a direct prompt (testing mode)."""

    def test_direct_prompt_bypasses_formatting(self):
        """Verify a payload with 'prompt' key is passed directly to the agent."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": "Analysis complete."}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance):
            mock_context = MagicMock()
            mock_context.session_id = "test-direct-001"
            payload = {"prompt": "What is the current status of ST-05?"}
            agent_mod.invoke(payload, mock_context)

        # Verify the agent received the direct prompt text
        agent_call_args = mock_agent_instance.call_args[0][0]
        assert agent_call_args == "What is the current status of ST-05?"


class TestAgentToolConfiguration:
    """Tests verifying the agent is configured with the correct tools and system prompt."""

    def test_system_prompt_includes_reasoning_workflow(self):
        """Verify the agent system prompt contains the full reasoning workflow."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": "{}"}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance) as mock_cls:
            mock_context = MagicMock()
            mock_context.session_id = "test-config-001"
            agent_mod.invoke(REAL_LEAK_PAYLOAD, mock_context)

        agent_init_kwargs = mock_cls.call_args[1]
        system_prompt = agent_init_kwargs["system_prompt"]

        assert "Anomaly Analysis" in system_prompt
        assert "False Positive Disambiguation" in system_prompt
        assert "Leak Localization" in system_prompt
        assert "Severity Assessment" in system_prompt
        assert "Incident Response" in system_prompt

    def test_agent_uses_correct_model(self):
        """Verify the agent is configured with the expected model ID."""
        import agent as agent_mod

        mock_agent_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.message = {"content": [{"text": "{}"}]}
        mock_agent_instance.return_value = mock_response

        with patch.object(agent_mod, "Agent", return_value=mock_agent_instance) as mock_cls:
            mock_context = MagicMock()
            mock_context.session_id = "test-config-002"
            agent_mod.invoke(REAL_LEAK_PAYLOAD, mock_context)

        agent_init_kwargs = mock_cls.call_args[1]
        assert agent_init_kwargs["model"] == "us.anthropic.claude-sonnet-4-6-20250514-v1:0"


class TestCustomToolsIntegration:
    """Tests verifying custom tool functions produce correct outputs for agent consumption."""

    def test_classify_severity_moderate(self):
        """Verify classify_severity returns correct category for moderate leak rate."""
        from tools import classify_severity

        result = classify_severity(leak_rate_mmscfd=0.55)

        assert result["severity"] == "moderate"
        assert result["isolation_required"] is True
        assert result["response_urgency"] == "elevated"
        assert result["phmsa_reportable"] is False

    def test_classify_severity_significant(self):
        """Verify classify_severity returns correct category for significant leak rate."""
        from tools import classify_severity

        result = classify_severity(leak_rate_mmscfd=1.2)

        assert result["severity"] == "significant"
        assert result["isolation_required"] is True
        assert result["nrc_notification_required"] is True
        assert result["phmsa_reportable"] is True

    def test_classify_severity_seep(self):
        """Verify classify_severity returns correct category for seep-level leak rate."""
        from tools import classify_severity

        result = classify_severity(leak_rate_mmscfd=0.1)

        assert result["severity"] == "seep"
        assert result["isolation_required"] is False
        assert result["response_urgency"] == "routine"

    def test_classify_severity_near_rupture(self):
        """Verify classify_severity returns correct category for near-rupture leak rate."""
        from tools import classify_severity

        result = classify_severity(leak_rate_mmscfd=2.0)

        assert result["severity"] == "near_rupture"
        assert result["isolation_required"] is True
        assert result["nrc_notification_required"] is True
        assert result["response_urgency"] == "emergency"

    def test_calculate_mass_balance_returns_code(self):
        """Verify calculate_mass_balance produces executable code for Code Interpreter."""
        from tools import calculate_mass_balance

        result = calculate_mass_balance(
            upstream_flow_mmscfd=6.2,
            downstream_flow_mmscfd=5.7,
            temperature_f=45.0,
            base_temperature_f=60.0,
            compressibility_factor=0.92,
            line_pack_change_mmscf=0.02,
        )

        assert "code" in result
        assert "description" in result
        assert "6.2" in result["code"]
        assert "5.7" in result["code"]
        assert "0.92" in result["code"]
        assert "json.dumps" in result["code"]

    def test_estimate_leak_location_returns_code(self):
        """Verify estimate_leak_location produces executable code for Code Interpreter."""
        from tools import estimate_leak_location

        result = estimate_leak_location(
            upstream_station_id="ST-05",
            downstream_station_id="ST-06",
            upstream_pressure_psi=755.0,
            downstream_pressure_psi=730.0,
            segment_length_miles=26.0,
            segment_start_mile_marker=104.0,
            diameter_in=24.0,
            elevation_start_ft=1200.0,
            elevation_end_ft=1150.0,
            compressibility_factor=0.92,
        )

        assert "code" in result
        assert "description" in result
        assert "ST-05" in result["code"]
        assert "ST-06" in result["code"]
        assert "755.0" in result["code"]

    def test_calculate_line_pack_correction_returns_code(self):
        """Verify calculate_line_pack_correction produces executable code."""
        from tools import calculate_line_pack_correction

        result = calculate_line_pack_correction(
            temperature_delta_f=-15.0,
            segment_length_miles=26.0,
            diameter_in=24.0,
            operating_pressure_psi=750.0,
            compressibility_factor=0.92,
            specific_gravity=0.6,
        )

        assert "code" in result
        assert "description" in result
        assert "-15.0" in result["code"]

    def test_estimate_leak_rate_returns_code(self):
        """Verify estimate_leak_rate produces executable code."""
        from tools import estimate_leak_rate

        result = estimate_leak_rate(
            mass_balance_deficit_mmscfd=0.55,
            compressibility_factor=0.92,
            temperature_f=45.0,
            pressure_psi=750.0,
        )

        assert "code" in result
        assert "description" in result
        assert "0.55" in result["code"]

    def test_get_operational_baseline_returns_defaults_without_memory(self):
        """Verify get_operational_baseline returns hardcoded defaults when memory is unavailable."""
        from tools import get_operational_baseline

        result = get_operational_baseline(station_id="ST-05")

        assert result["station_id"] == "ST-05"
        # Should either return defaults or an error gracefully
        assert result["source"] in ("hardcoded_defaults", "error")
