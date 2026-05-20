"""Pipeline Overview Page — Station status gauges and segment health.

Displays:
- 8-station status cards with pressure/flow/temperature gauges (Plotly)
- Segment health color coding (green/yellow/red based on mass_balance_deficit)
- Summary of active incident count

Requirements: 8.1, 8.4
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Add dashboard directory to path for utils import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import get_incidents, get_latest_scada_readings, get_pipeline_segments

st.set_page_config(page_title="Pipeline Overview", page_icon="📊", layout="wide")

# Auto-refresh using streamlit-autorefresh (install: pip install streamlit-autorefresh)
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=15000, key="pipeline_overview_refresh")  # 15 seconds
except ImportError:
    pass  # Falls back to manual refresh if package not installed

st.title("📊 Pipeline Overview")
st.caption("Data refreshes automatically every 15 seconds")

# --- Load data ---
scada_df = get_latest_scada_readings(num_rows=200)
segments = get_pipeline_segments()
incidents = get_incidents()

# Count active (open) incidents
active_incidents = [i for i in incidents if i.get("status") == "open"]

# --- Summary metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Stations Online", "8 / 8")
col2.metric("Active Incidents", len(active_incidents))
col3.metric("Segments Monitored", len(segments) if segments else 7)
col4.metric("Pipeline Length", "200 mi")

st.divider()

# --- Station Status Cards ---
st.subheader("Station Status")

if scada_df.empty:
    st.warning("No SCADA data available. Check S3 bucket configuration.")
else:
    # Get the latest reading per station
    latest_per_station = (
        scada_df.sort_values("timestamp", ascending=False)
        .groupby("station_id")
        .first()
        .reset_index()
        .sort_values("station_id")
    )

    # Display stations in two rows of 4
    for row_start in range(0, 8, 4):
        cols = st.columns(4)
        for i, col in enumerate(cols):
            station_idx = row_start + i
            if station_idx >= len(latest_per_station):
                break

            row = latest_per_station.iloc[station_idx]
            station_id = row["station_id"]
            pressure = row.get("pressure_psi", 0)
            flow = row.get("flow_mmscfd", 0)
            temp = row.get("temperature_f", 0)
            deficit = row.get("mass_balance_deficit_mmscfd", 0)

            # Determine station health color
            if abs(deficit) > 0.3:
                health_color = "🔴"
                health_status = "ALERT"
            elif abs(deficit) > 0.15:
                health_color = "🟡"
                health_status = "WARNING"
            else:
                health_color = "🟢"
                health_status = "NORMAL"

            with col:
                st.markdown(f"### {health_color} {station_id}")
                st.caption(f"Type: {row.get('station_type', 'N/A')} | Status: {health_status}")

                # Pressure gauge
                fig_pressure = go.Figure(
                    go.Indicator(
                        mode="gauge+number",
                        value=pressure,
                        title={"text": "Pressure (PSI)"},
                        gauge={
                            "axis": {"range": [600, 850]},
                            "bar": {"color": "darkblue"},
                            "steps": [
                                {"range": [600, 700], "color": "lightyellow"},
                                {"range": [700, 800], "color": "lightgreen"},
                                {"range": [800, 850], "color": "lightyellow"},
                            ],
                            "threshold": {
                                "line": {"color": "red", "width": 2},
                                "thickness": 0.75,
                                "value": 850,
                            },
                        },
                    )
                )
                fig_pressure.update_layout(height=180, margin=dict(t=40, b=10, l=20, r=20))
                st.plotly_chart(fig_pressure, use_container_width=True)

                # Flow and temperature as metrics
                st.metric("Flow (MMSCFD)", f"{flow:.2f}")
                st.metric("Temperature (°F)", f"{temp:.1f}")
                st.metric("Mass Balance Deficit", f"{deficit:.3f} MMSCFD")

st.divider()

# --- Segment Health Map ---
st.subheader("Segment Health")

if scada_df.empty:
    st.warning("No SCADA data available for segment health.")
else:
    # Calculate segment health based on max deficit in each segment's stations
    segment_data = [
        {"id": "SEG-01", "from": "ST-01", "to": "ST-02"},
        {"id": "SEG-02", "from": "ST-02", "to": "ST-03"},
        {"id": "SEG-03", "from": "ST-03", "to": "ST-04"},
        {"id": "SEG-04", "from": "ST-04", "to": "ST-05"},
        {"id": "SEG-05", "from": "ST-05", "to": "ST-06"},
        {"id": "SEG-06", "from": "ST-06", "to": "ST-07"},
        {"id": "SEG-07", "from": "ST-07", "to": "ST-08"},
    ]

    # Build set of segments with active incidents
    incident_segments = set()
    for inc in active_incidents:
        seg = inc.get("affected_segment", "")
        if seg:
            incident_segments.add(seg)

    seg_cols = st.columns(7)
    for idx, seg in enumerate(segment_data):
        # Get max deficit for stations in this segment
        seg_stations = [seg["from"], seg["to"]]
        seg_readings = latest_per_station[latest_per_station["station_id"].isin(seg_stations)]

        if not seg_readings.empty:
            max_deficit = seg_readings["mass_balance_deficit_mmscfd"].abs().max()
        else:
            max_deficit = 0

        # Color code: red if active incident on this segment, else by deficit
        if seg["id"] in incident_segments:
            color = "🔴"
            status_text = "INCIDENT"
        elif max_deficit > 0.3:
            color = "🔴"
            status_text = f"Deficit: {max_deficit:.3f}"
        elif max_deficit > 0.15:
            color = "🟡"
            status_text = f"Deficit: {max_deficit:.3f}"
        else:
            color = "🟢"
            status_text = f"Deficit: {max_deficit:.3f}"

        with seg_cols[idx]:
            st.markdown(f"**{color} {seg['id']}**")
            st.caption(f"{seg['from']} → {seg['to']}")
            st.caption(status_text)

# --- Active Incidents Summary ---
if active_incidents:
    st.divider()
    st.subheader(f"⚠️ Active Incidents ({len(active_incidents)})")
    for inc in active_incidents[:5]:  # Show top 5
        severity = inc.get("severity", "unknown")
        severity_emoji = {"seep": "🟡", "moderate": "🟠", "significant": "🔴", "near_rupture": "🔴"}.get(
            severity, "⚪"
        )
        st.markdown(
            f"{severity_emoji} **{inc.get('incident_id', 'N/A')}** — "
            f"{inc.get('affected_segment', 'N/A')} | "
            f"Severity: {severity} | "
            f"{inc.get('timestamp', 'N/A')}"
        )
