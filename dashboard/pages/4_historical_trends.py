"""Historical Trends Page — Time-series charts for pressure and flow.

Displays:
- Plotly line charts for pressure and flow at user-selected stations
- Configurable time window
- Station selector dropdown

Requirements: 8.1
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import get_scada_history

st.set_page_config(page_title="Historical Trends", page_icon="📈", layout="wide")
st.title("📈 Historical Trends")

# --- Controls ---
ALL_STATIONS = ["ST-01", "ST-02", "ST-03", "ST-04", "ST-05", "ST-06", "ST-07", "ST-08"]

col1, col2 = st.columns(2)
with col1:
    selected_stations = st.multiselect(
        "Select Stations",
        options=ALL_STATIONS,
        default=["ST-05", "ST-06"],
    )
with col2:
    time_window = st.selectbox(
        "Time Window",
        options=[6, 12, 24, 48, 72, 168],
        index=2,
        format_func=lambda x: f"{x} hours" if x < 48 else f"{x // 24} days",
    )

if not selected_stations:
    st.warning("Select at least one station to view trends.")
    st.stop()

# --- Load data ---
df = get_scada_history(station_ids=selected_stations, hours=time_window)

if df.empty:
    st.warning("No SCADA data available for the selected stations and time window.")
    st.stop()

st.caption(f"Showing {len(df)} readings from {df['timestamp'].min()} to {df['timestamp'].max()}")
st.divider()

# --- Pressure Trend ---
st.subheader("Pressure (PSI)")
fig_pressure = px.line(
    df,
    x="timestamp",
    y="pressure_psi",
    color="station_id",
    title="Station Pressure Over Time",
    labels={"pressure_psi": "Pressure (PSI)", "timestamp": "Time", "station_id": "Station"},
)
fig_pressure.update_layout(height=400, hovermode="x unified")
# Add MAOP reference line
fig_pressure.add_hline(y=850, line_dash="dash", line_color="red", annotation_text="MAOP (850 PSI)")
# Add normal operating range band
fig_pressure.add_hrect(y0=700, y1=800, fillcolor="green", opacity=0.05, line_width=0)
st.plotly_chart(fig_pressure, use_container_width=True)

# --- Flow Trend ---
st.subheader("Flow Rate (MMSCFD)")
fig_flow = px.line(
    df,
    x="timestamp",
    y="flow_mmscfd",
    color="station_id",
    title="Station Flow Rate Over Time",
    labels={"flow_mmscfd": "Flow (MMSCFD)", "timestamp": "Time", "station_id": "Station"},
)
fig_flow.update_layout(height=400, hovermode="x unified")
# Add normal flow range band
fig_flow.add_hrect(y0=5.5, y1=6.5, fillcolor="green", opacity=0.05, line_width=0)
st.plotly_chart(fig_flow, use_container_width=True)

# --- Mass Balance Deficit Trend ---
st.subheader("Mass Balance Deficit (MMSCFD)")
fig_deficit = px.line(
    df,
    x="timestamp",
    y="mass_balance_deficit_mmscfd",
    color="station_id",
    title="Mass Balance Deficit Over Time",
    labels={
        "mass_balance_deficit_mmscfd": "Deficit (MMSCFD)",
        "timestamp": "Time",
        "station_id": "Station",
    },
)
fig_deficit.update_layout(height=400, hovermode="x unified")
# Add alert threshold
fig_deficit.add_hline(y=0.3, line_dash="dash", line_color="orange", annotation_text="Alert Threshold (0.3)")
fig_deficit.add_hline(y=-0.3, line_dash="dash", line_color="orange")
st.plotly_chart(fig_deficit, use_container_width=True)

# --- Temperature Trend ---
with st.expander("Temperature Trend"):
    fig_temp = px.line(
        df,
        x="timestamp",
        y="temperature_f",
        color="station_id",
        title="Ambient Temperature Over Time",
        labels={"temperature_f": "Temperature (°F)", "timestamp": "Time", "station_id": "Station"},
    )
    fig_temp.update_layout(height=350, hovermode="x unified")
    st.plotly_chart(fig_temp, use_container_width=True)
