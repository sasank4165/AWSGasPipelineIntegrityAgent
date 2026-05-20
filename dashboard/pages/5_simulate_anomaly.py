"""Simulate Anomaly Page — Trigger scenarios or custom payloads.

Provides pre-built scenarios plus a custom JSON editor to invoke the
Pipeline Integrity Agent and display results.
"""

import json
import re
import sys
import time
import uuid
from pathlib import Path

import boto3
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(page_title="Simulate Anomaly", page_icon="🧪", layout="wide")
st.title("🧪 Simulate Anomaly")
st.markdown(
    "Trigger a pre-built anomaly scenario or enter a custom payload. "
    "The agent performs a full multi-step investigation with 10-15 tool calls."
)
st.caption("⏱️ Expected response time: 1-3 minutes.")

# --- Configuration ---
REGION = "us-west-2"
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:211125430374:runtime/pipeline_integrity_agent-1ZMVK49mbl"

# --- Reference ranges ---
with st.expander("📋 Reference: Normal Operating Ranges"):
    st.markdown("""
| Parameter | Normal Range | Alert Threshold |
|-----------|-------------|-----------------|
| Line Pressure | 700–800 PSI | < 700 or > 820 PSI |
| Flow Rate | 5.5–6.5 MMSCFD | Deviation > 0.5 MMSCFD |
| Mass Balance Deficit | < 0.1 MMSCFD | > 0.3 MMSCFD |
| Pressure Drop Rate | < 0.5 PSI/min | > 1.5 PSI/min sustained 5 min |
| Temperature | 35–75 °F (seasonal) | Δ > 15°F in 6 hours |
| MAOP | 850 PSI | Never exceed |

**Stations:** ST-01 (MM 0), ST-02 (MM 28), ST-03 (MM 52), ST-04 (MM 78), ST-05 (MM 104), ST-06 (MM 130), ST-07 (MM 158), ST-08 (MM 200)

**Segments:** SEG-01 through SEG-07 (between adjacent stations)

**Severity Thresholds:**
- Seep: < 0.25 MMSCFD
- Moderate: 0.25–0.75 MMSCFD
- Significant: 0.75–1.5 MMSCFD
- Near-rupture: > 1.5 MMSCFD
""")

st.divider()


# --- Helper functions ---
def invoke_agent(payload: dict) -> str:
    """Invoke the Pipeline Integrity Agent via AgentCore Runtime."""
    try:
        from botocore.config import Config

        config = Config(read_timeout=600, connect_timeout=10, retries={"max_attempts": 0})
        client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)
        session_id = f"dashboard-simulation-{uuid.uuid4().hex}"

        response = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            payload=json.dumps(payload).encode("utf-8"),
            qualifier="DEFAULT",
            runtimeSessionId=session_id,
        )

        if "response" in response:
            return response["response"].read().decode("utf-8")
        elif "body" in response:
            return response["body"].read().decode("utf-8")
        else:
            return json.dumps({k: str(v)[:200] for k, v in response.items() if k != "ResponseMetadata"})
    except Exception as e:
        return f"Error invoking agent: {str(e)}"


def render_response(raw: str) -> None:
    """Render the agent response in a clean, readable format."""
    text = raw.replace("\\n", "\n").replace("\\t", "\t")
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    json_blocks = re.findall(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_blocks:
        parts = re.split(r'```json\s*.*?\s*```', text, flags=re.DOTALL)
        for i, part in enumerate(parts):
            if part.strip():
                st.markdown(part.strip())
            if i < len(json_blocks):
                try:
                    st.json(json.loads(json_blocks[i]))
                except json.JSONDecodeError:
                    st.code(json_blocks[i], language="json")
    else:
        st.markdown(text)


# --- Tabs for different input modes ---
tab1, tab2 = st.tabs(["🎯 Pre-built Scenarios", "✏️ Custom Payload"])

with tab1:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🔴 Real Leak — Significant")
        st.markdown("18 PSI drop in 5 min at ST-05/ST-06. 1.2 MMSCFD deficit. No operational cause.")
        run_leak = st.button("🚨 Trigger Real Leak", type="primary", use_container_width=True)

    with col2:
        st.subheader("🟡 False Positive — Temperature")
        st.markdown("8.5 PSI drop over 12 min at ST-03/ST-04. Overnight cooling + compressor event.")
        run_fp = st.button("⚡ Trigger False Positive", use_container_width=True)

    if run_leak:
        payload = {
            "event_id": f"SIM-LEAK-{int(time.time())}",
            "timestamp": "2025-12-04T23:55:00Z",
            "anomaly_type": "mass_balance_deficit",
            "affected_stations": ["ST-05", "ST-06"],
            "affected_segment": "SEG-05",
            "trigger_values": {
                "pressure_drop_psi": 18.0,
                "duration_minutes": 5,
                "pressure_drop_rate_psi_per_min": 3.6,
                "mass_balance_deficit_mmscfd": 1.2,
            },
            "severity": "critical",
        }
        st.subheader("🔍 Agent Investigation in Progress...")
        with st.spinner("Running full 5-step investigation (typically 1-3 minutes)..."):
            start = time.time()
            response = invoke_agent(payload)
            elapsed = time.time() - start
        st.success(f"Agent responded in {elapsed:.1f} seconds")
        render_response(response)

    elif run_fp:
        payload = {
            "event_id": f"SIM-FP-{int(time.time())}",
            "timestamp": "2025-12-10T06:30:00Z",
            "anomaly_type": "pressure_drop",
            "affected_stations": ["ST-03", "ST-04"],
            "affected_segment": "SEG-03",
            "trigger_values": {
                "pressure_drop_psi": 8.5,
                "duration_minutes": 12,
                "pressure_drop_rate_psi_per_min": 0.71,
                "mass_balance_deficit_mmscfd": 0.28,
            },
            "severity": "warning",
        }
        st.subheader("🔍 Agent Investigation in Progress...")
        with st.spinner("Running false positive disambiguation (typically 1-2 minutes)..."):
            start = time.time()
            response = invoke_agent(payload)
            elapsed = time.time() - start
        st.success(f"Agent responded in {elapsed:.1f} seconds")
        render_response(response)

with tab2:
    st.markdown("Enter a custom anomaly event payload. Edit the JSON below and click **Invoke Agent**.")

    default_payload = json.dumps({
        "event_id": f"CUSTOM-{int(time.time())}",
        "timestamp": "2025-12-15T14:30:00Z",
        "anomaly_type": "pressure_drop",
        "affected_stations": ["ST-05", "ST-06"],
        "affected_segment": "SEG-05",
        "trigger_values": {
            "pressure_drop_psi": 12.0,
            "duration_minutes": 8,
            "pressure_drop_rate_psi_per_min": 1.5,
            "mass_balance_deficit_mmscfd": 0.52,
        },
        "severity": "warning",
    }, indent=2)

    custom_json = st.text_area(
        "Anomaly Event Payload (JSON)",
        value=default_payload,
        height=300,
    )

    run_custom = st.button("🚀 Invoke Agent", type="primary", use_container_width=True)

    if run_custom:
        try:
            payload = json.loads(custom_json)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
            st.stop()

        st.subheader("🔍 Agent Investigation in Progress...")
        with st.spinner("Running investigation (typically 1-3 minutes)..."):
            start = time.time()
            response = invoke_agent(payload)
            elapsed = time.time() - start
        st.success(f"Agent responded in {elapsed:.1f} seconds")
        render_response(response)
