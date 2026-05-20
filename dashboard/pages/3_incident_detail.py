"""Incident Detail Page — Full agent reasoning timeline for a selected incident.

Displays the complete investigation chain:
- Anomaly trigger values
- False positive checks performed
- Localization results
- Severity assessment
- Recommended actions

Requirements: 8.3
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import get_incidents

st.set_page_config(page_title="Incident Detail", page_icon="🔍", layout="wide")
st.title("🔍 Incident Detail")

# --- Load incidents ---
incidents = get_incidents()

if not incidents:
    st.info("No incidents recorded yet.")
    st.stop()

# --- Incident selector ---
incident_ids = [i.get("incident_id", "N/A") for i in incidents]
selected_id = st.selectbox("Select Incident", options=incident_ids)

# Find the selected incident
selected_incident = next((i for i in incidents if i.get("incident_id") == selected_id), None)

if not selected_incident:
    st.error("Incident not found.")
    st.stop()

inc = selected_incident

# --- Header ---
classification = inc.get("classification", "unknown")
severity = inc.get("severity", "unknown")
severity_emoji = {"seep": "🟡", "moderate": "🟠", "significant": "🔴", "near_rupture": "🔴"}.get(severity, "⚪")

if classification == "real_leak":
    st.error(f"{severity_emoji} **CONFIRMED LEAK** — Severity: {severity.upper()}")
else:
    st.success("✅ **FALSE POSITIVE** — Event dismissed")

# --- Summary metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Incident ID", inc.get("incident_id", "N/A"))
col2.metric("Timestamp", inc.get("timestamp", "N/A")[:19])
col3.metric("Response Time", f"{inc.get('response_time_seconds', '—')}s")
col4.metric("Status", inc.get("status", "unknown").upper())

st.divider()

# --- Agent Reasoning Timeline ---
st.subheader("Agent Reasoning Timeline")

# Step 1: Anomaly Analysis
st.markdown("### Step 1: Anomaly Analysis")
anomaly = inc.get("anomaly_analysis", {})
if anomaly:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Trigger Type:** `{anomaly.get('trigger_type', 'N/A')}`")
        stations = anomaly.get("affected_stations", [])
        st.markdown(f"**Affected Stations:** {', '.join(stations)}")
        st.markdown(f"**Affected Segment:** `{anomaly.get('affected_segment', 'N/A')}`")
    with col2:
        st.markdown("**Readings:**")
        readings = anomaly.get("readings", {})
        if readings:
            for key, val in readings.items():
                st.markdown(f"- {key}: `{val}`")
        deviation = anomaly.get("deviation_from_normal", {})
        if deviation:
            st.markdown("**Deviation from Normal:**")
            for key, val in deviation.items():
                st.markdown(f"- {key}: `{val}`")
else:
    st.caption("No anomaly analysis data recorded.")

st.divider()

# Step 2: False Positive Disambiguation
st.markdown("### Step 2: False Positive Disambiguation")
fp_check = inc.get("false_positive_check", {})
if fp_check:
    # Compressor check
    comp = fp_check.get("compressor_check", {})
    if isinstance(comp, dict):
        icon = "✅" if comp.get("performed") else "⏭️"
        st.markdown(f"{icon} **Compressor Event Check**")
        st.markdown(f"   Finding: {comp.get('finding', 'N/A')}")
    
    # Valve check
    valve = fp_check.get("valve_check", {})
    if isinstance(valve, dict):
        icon = "✅" if valve.get("performed") else "⏭️"
        st.markdown(f"{icon} **Valve Position Check**")
        st.markdown(f"   Finding: {valve.get('finding', 'N/A')}")
    
    # Temperature check
    temp = fp_check.get("temperature_check", {})
    if isinstance(temp, dict):
        icon = "✅" if temp.get("performed") else "⏭️"
        st.markdown(f"{icon} **Temperature / Line Pack Check**")
        st.markdown(f"   Finding: {temp.get('finding', 'N/A')}")

    # Residual deficit
    residual = fp_check.get("residual_deficit_mmscfd")
    if residual is not None:
        try:
            residual_val = float(residual)
        except (ValueError, TypeError):
            residual_val = 0.0
        threshold_met = residual_val < 0.2
        if threshold_met:
            st.info(f"Residual deficit: **{residual} MMSCFD** (below 0.2 threshold → false positive)")
        else:
            st.warning(f"Residual deficit: **{residual} MMSCFD** (above 0.2 threshold → proceed to localization)")

    # Reasoning summary
    reasoning = fp_check.get("reasoning")
    if reasoning:
        st.markdown(f"**Reasoning:** {reasoning}")
else:
    st.caption("No false positive check data recorded.")

st.divider()

# Step 3: Leak Localization (only for real leaks)
if classification == "real_leak":
    st.markdown("### Step 3: Leak Localization")
    localization = inc.get("leak_localization", {})
    if localization:
        col1, col2, col3 = st.columns(3)
        col1.metric("Segment", localization.get("segment", "N/A"))
        mm_range = localization.get("mile_marker_range", [])
        if mm_range and len(mm_range) == 2:
            col2.metric("Mile Marker Range", f"MM {mm_range[0]} – {mm_range[1]}")
        col3.metric("Confidence", f"±{localization.get('confidence_miles', 'N/A')} mi")
    else:
        st.caption("No localization data available.")

    st.divider()

    # Step 4: Severity Assessment
    st.markdown("### Step 4: Severity Assessment")
    col1, col2, col3 = st.columns(3)
    col1.metric("Severity", severity.upper() if severity else "N/A")
    col2.metric("Leak Rate", f"{inc.get('leak_rate_mmscfd', 'N/A')} MMSCFD")
    phmsa = inc.get("phmsa_reportable", False)
    col3.metric("PHMSA Reportable", "⚠️ YES" if phmsa else "No")

    if phmsa:
        st.warning("This incident requires NRC notification within 1 hour (49 CFR 191.5).")

    st.divider()

    # Step 5: Incident Response
    st.markdown("### Step 5: Incident Response")
    actions = inc.get("recommended_actions", [])
    if actions:
        st.markdown("**Recommended Actions:**")
        for i, action in enumerate(actions, 1):
            st.markdown(f"{i}. {action}")
    else:
        st.caption("No recommended actions recorded.")

    # Draft notification
    draft = inc.get("draft_notification")
    if draft:
        st.markdown("**Draft PHMSA Notification:**")
        st.code(draft, language="text")
else:
    st.markdown("### Resolution")
    st.success(
        "Event classified as **false positive**. No leak localization, severity assessment, "
        "or incident response actions were required."
    )

# --- Raw JSON (collapsible) ---
st.divider()
with st.expander("View raw incident data (JSON)"):
    st.json(inc)
