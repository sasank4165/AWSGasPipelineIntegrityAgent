"""Active Incidents Page — Sortable table of all incidents.

Displays:
- Sortable table of all incidents from DynamoDB
- Color-coded severity badges
- Timestamps and affected segments
- Link to incident detail view

Requirements: 8.2, 8.3
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import get_incidents

st.set_page_config(page_title="Active Incidents", page_icon="⚠️", layout="wide")
st.title("⚠️ Active Incidents")


# --- Helper function (must be defined before use) ---
def _render_incident_detail(inc: dict) -> None:
    """Render the full agent reasoning timeline for a single incident."""
    classification = inc.get("classification", "unknown")
    if classification == "real_leak":
        st.error("**Classification:** Real Leak Confirmed")
    else:
        st.success("**Classification:** False Positive (dismissed)")

    # Anomaly Analysis
    st.markdown("#### 1. Anomaly Trigger")
    anomaly = inc.get("anomaly_analysis", {})
    if anomaly:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Trigger Type:** {anomaly.get('trigger_type', 'N/A')}")
            st.markdown(f"**Affected Stations:** {', '.join(anomaly.get('affected_stations', []))}")
            st.markdown(f"**Affected Segment:** {anomaly.get('affected_segment', 'N/A')}")
        with col2:
            readings = anomaly.get("readings", {})
            if readings:
                st.json(readings)
    else:
        st.caption("No anomaly analysis data available.")

    # False Positive Checks
    st.markdown("#### 2. False Positive Checks")
    fp_check = inc.get("false_positive_check", {})
    if fp_check:
        checks = [
            ("Compressor Check", fp_check.get("compressor_check", {})),
            ("Valve Check", fp_check.get("valve_check", {})),
            ("Temperature Check", fp_check.get("temperature_check", {})),
        ]
        for check_name, check_data in checks:
            if isinstance(check_data, dict):
                performed = "✅" if check_data.get("performed") else "❌"
                finding = check_data.get("finding", "No data")
                st.markdown(f"- {performed} **{check_name}:** {finding}")
            else:
                st.markdown(f"- **{check_name}:** {check_data}")

        residual = fp_check.get("residual_deficit_mmscfd")
        if residual is not None:
            st.markdown(f"- **Residual Deficit:** {residual} MMSCFD")
    else:
        st.caption("No false positive check data available.")

    # Leak Localization (only for real leaks)
    if classification == "real_leak":
        st.markdown("#### 3. Leak Localization")
        localization = inc.get("leak_localization", {})
        if localization:
            st.markdown(f"**Segment:** {localization.get('segment', 'N/A')}")
            mm_range = localization.get("mile_marker_range", [])
            if mm_range:
                st.markdown(f"**Mile Marker Range:** {mm_range[0]} – {mm_range[1]}")
            st.markdown(f"**Confidence:** ±{localization.get('confidence_miles', 'N/A')} miles")
        else:
            st.caption("No localization data available.")

        st.markdown("#### 4. Severity Assessment")
        st.markdown(f"**Severity:** {inc.get('severity', 'N/A')}")
        st.markdown(f"**Leak Rate:** {inc.get('leak_rate_mmscfd', 'N/A')} MMSCFD")
        st.markdown(f"**PHMSA Reportable:** {'Yes ⚠️' if inc.get('phmsa_reportable') else 'No'}")

    # Recommended Actions
    actions = inc.get("recommended_actions", [])
    if actions:
        st.markdown("#### 5. Recommended Actions")
        for action in actions:
            st.markdown(f"- {action}")

    response_time = inc.get("response_time_seconds")
    if response_time:
        st.caption(f"Agent response time: {response_time} seconds")


# --- Load incidents ---
incidents = get_incidents()

if not incidents:
    st.info("No incidents recorded yet. The agent creates incidents when real leaks are confirmed.")
    st.stop()

# --- Filter controls ---
col1, col2 = st.columns(2)
with col1:
    status_filter = st.selectbox(
        "Filter by status",
        options=["all", "open", "investigating", "resolved"],
        index=0,
    )
with col2:
    severity_filter = st.selectbox(
        "Filter by severity",
        options=["all", "seep", "moderate", "significant", "near_rupture"],
        index=0,
    )

# Apply filters
filtered = incidents
if status_filter != "all":
    filtered = [i for i in filtered if i.get("status") == status_filter]
if severity_filter != "all":
    filtered = [i for i in filtered if i.get("severity") == severity_filter]

st.markdown(f"Showing **{len(filtered)}** of {len(incidents)} incidents")
st.divider()

# --- Incidents table ---
if filtered:
    table_data = []
    for inc in filtered:
        severity = inc.get("severity", "—")
        severity_badge = {
            "seep": "🟡 Seep",
            "moderate": "🟠 Moderate",
            "significant": "🔴 Significant",
            "near_rupture": "🔴 Near-Rupture",
        }.get(severity, "⚪ Unknown")

        status = inc.get("status", "unknown")
        status_badge = {
            "open": "🔓 Open",
            "investigating": "🔍 Investigating",
            "resolved": "✅ Resolved",
        }.get(status, status)

        table_data.append({
            "Incident ID": inc.get("incident_id", "N/A"),
            "Timestamp": inc.get("timestamp", "N/A"),
            "Classification": inc.get("classification", "N/A"),
            "Severity": severity_badge,
            "Segment": inc.get("affected_segment", "N/A"),
            "Status": status_badge,
            "PHMSA Reportable": "⚠️ Yes" if inc.get("phmsa_reportable") else "No",
            "Response Time (s)": inc.get("response_time_seconds", "—"),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Incident detail expanders ---
    st.divider()
    st.subheader("Incident Details")
    st.caption("Expand an incident below to view the agent's full reasoning timeline.")

    for inc in filtered:
        incident_id = inc.get("incident_id", "N/A")
        severity = inc.get("severity", "unknown")
        severity_emoji = {"seep": "🟡", "moderate": "🟠", "significant": "🔴", "near_rupture": "🔴"}.get(
            severity, "⚪"
        )

        with st.expander(f"{severity_emoji} {incident_id} — {inc.get('affected_segment', '')} ({inc.get('timestamp', '')})"):
            _render_incident_detail(inc)
else:
    st.info("No incidents match the current filters.")
