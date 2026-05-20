"""Custom tool functions for the Pipeline Integrity Agent.

These tools perform physics-based calculations for leak detection and analysis.
Each tool prepares a Python code string and invokes the AgentCore Code Interpreter
for sandboxed execution, ensuring reproducible and auditable calculations.

Tools:
- calculate_mass_balance: Corrected mass balance deficit between stations
- estimate_leak_location: Mile marker range using pressure gradient analysis
- calculate_line_pack_correction: Temperature-driven line pack change
- estimate_leak_rate: Leak rate from mass balance deficit
- classify_severity: Severity category from leak rate
"""

from strands import tool


@tool
def calculate_mass_balance(
    upstream_flow_mmscfd: float,
    downstream_flow_mmscfd: float,
    temperature_f: float,
    base_temperature_f: float,
    compressibility_factor: float,
    line_pack_change_mmscf: float,
) -> dict:
    """Calculate the temperature-and-compressibility-corrected mass balance deficit between two stations.

    Uses real gas law corrections to determine the true deficit after accounting for
    temperature effects on gas density and compressibility deviations from ideal behavior.
    A positive deficit indicates more gas entering the segment than leaving — potential leak.

    Args:
        upstream_flow_mmscfd: Flow rate at the upstream station in MMSCFD.
        downstream_flow_mmscfd: Flow rate at the downstream station in MMSCFD.
        temperature_f: Current ambient temperature in Fahrenheit.
        base_temperature_f: Base/reference temperature for flow measurement (typically 60°F).
        compressibility_factor: Gas compressibility factor Z (from gas composition analysis).
        line_pack_change_mmscf: Change in line pack over the measurement interval in MMSCF.
    """
    # The Code Interpreter will execute this calculation in a sandboxed environment.
    # We build the code string with the actual parameter values injected.
    code = f"""
import json

# Input parameters
upstream_flow = {upstream_flow_mmscfd}  # MMSCFD at upstream station
downstream_flow = {downstream_flow_mmscfd}  # MMSCFD at downstream station
temperature_f = {temperature_f}  # Current ambient temperature (°F)
base_temperature_f = {base_temperature_f}  # Base temperature for measurement (°F)
compressibility_z = {compressibility_factor}  # Gas compressibility factor
line_pack_change = {line_pack_change_mmscf}  # Line pack change over interval (MMSCF)

# Convert temperatures to Rankine for gas law calculations
temperature_r = temperature_f + 459.67
base_temperature_r = base_temperature_f + 459.67

# Temperature correction factor: adjusts flow to standard conditions
# Real gas at different temperatures occupies different volumes
temp_correction = base_temperature_r / temperature_r

# Compressibility correction: accounts for non-ideal gas behavior
# Z < 1 means gas is more compressible than ideal (common for natural gas at high pressure)
z_correction = 1.0 / compressibility_z

# Apply corrections to both flow measurements
corrected_upstream = upstream_flow * temp_correction * z_correction
corrected_downstream = downstream_flow * temp_correction * z_correction

# Raw deficit: difference between what enters and what leaves the segment
raw_deficit = corrected_upstream - corrected_downstream

# Subtract line pack change: gas stored in the pipe due to pressure/temp changes
# is not lost gas — it's just temporarily stored in the segment
corrected_deficit = raw_deficit - line_pack_change

result = {{
    "raw_deficit_mmscfd": round(raw_deficit, 4),
    "corrected_deficit_mmscfd": round(corrected_deficit, 4),
    "temp_correction_factor": round(temp_correction, 6),
    "z_correction_factor": round(z_correction, 6),
    "interpretation": "potential_leak" if corrected_deficit > 0.2 else "within_normal"
}}
print(json.dumps(result))
"""
    # Return the code for the agent to execute via Code Interpreter
    return {
        "code": code,
        "description": "Mass balance calculation with temperature and compressibility corrections. Execute this code in the Code Interpreter to get the corrected deficit.",
    }



@tool
def estimate_leak_location(
    upstream_station_id: str,
    downstream_station_id: str,
    upstream_pressure_psi: float,
    downstream_pressure_psi: float,
    segment_length_miles: float,
    segment_start_mile_marker: float,
    diameter_in: float,
    elevation_start_ft: float,
    elevation_end_ft: float,
    compressibility_factor: float,
) -> dict:
    """Estimate the physical location of a leak as a mile marker range using pressure gradient analysis.

    Uses the pressure profile between two bounding stations to estimate where the
    leak is occurring. A leak causes a steeper pressure drop upstream of the leak
    point and a flatter gradient downstream. The intersection of these gradients
    gives the estimated leak location.

    Args:
        upstream_station_id: ID of the upstream bounding station (e.g., "ST-05").
        downstream_station_id: ID of the downstream bounding station (e.g., "ST-06").
        upstream_pressure_psi: Current pressure at the upstream station in PSI.
        downstream_pressure_psi: Current pressure at the downstream station in PSI.
        segment_length_miles: Length of the pipeline segment in miles.
        segment_start_mile_marker: Mile marker at the upstream station.
        diameter_in: Pipeline internal diameter in inches.
        elevation_start_ft: Elevation at the upstream station in feet.
        elevation_end_ft: Elevation at the downstream station in feet.
        compressibility_factor: Gas compressibility factor Z.
    """
    code = f"""
import json

# Input parameters
upstream_station = "{upstream_station_id}"
downstream_station = "{downstream_station_id}"
p_upstream = {upstream_pressure_psi}  # PSI at upstream station
p_downstream = {downstream_pressure_psi}  # PSI at downstream station
segment_length = {segment_length_miles}  # miles
start_mile_marker = {segment_start_mile_marker}  # mile marker of upstream station
diameter = {diameter_in}  # inches
elev_start = {elevation_start_ft}  # feet
elev_end = {elevation_end_ft}  # feet
z_factor = {compressibility_factor}

# Elevation correction: convert elevation difference to equivalent pressure head
# For natural gas, pressure change due to elevation is small but non-negligible
# Using simplified gas column formula: dP = 0.0375 * SG * dH / (T * Z)
# Assuming SG ≈ 0.6 for natural gas, T ≈ 520°R
specific_gravity = 0.6
avg_temp_rankine = 520.0
elevation_diff = elev_end - elev_start
elevation_pressure_correction = 0.0375 * specific_gravity * elevation_diff / (avg_temp_rankine * z_factor)

# Correct downstream pressure for elevation effects
p_downstream_corrected = p_downstream - elevation_pressure_correction

# Calculate the overall pressure gradient (PSI per mile) for the segment
# Under normal flow (no leak), pressure drops linearly along the pipe
total_pressure_drop = p_upstream - p_downstream_corrected
normal_gradient = total_pressure_drop / segment_length  # PSI/mile

# Leak location estimation using pressure ratio method:
# The leak creates a discontinuity in the pressure profile.
# Assuming the leak splits the segment into two sub-segments with different
# flow rates, the pressure at the leak point can be estimated.
# The fractional distance to the leak from upstream is approximately:
# x/L = (P_upstream - P_leak) / (P_upstream - P_downstream)
# For a moderate leak, the pressure at the leak point is approximately
# the geometric mean of the two station pressures (simplified model).
p_leak_estimate = (p_upstream + p_downstream_corrected) / 2.0

# Fractional position along segment (0 = upstream station, 1 = downstream station)
if total_pressure_drop > 0:
    fractional_position = (p_upstream - p_leak_estimate) / total_pressure_drop
else:
    fractional_position = 0.5  # Default to midpoint if no pressure drop

# Clamp to valid range
fractional_position = max(0.1, min(0.9, fractional_position))

# Convert to mile marker
estimated_mile_marker = start_mile_marker + (fractional_position * segment_length)

# Confidence interval: depends on segment length and pressure measurement quality
# Longer segments and smaller pressure differences = less confidence
# Rule of thumb: confidence ≈ segment_length * 0.15 (±15% of segment length)
pressure_ratio = total_pressure_drop / p_upstream if p_upstream > 0 else 0
if pressure_ratio > 0.05:
    confidence_miles = segment_length * 0.10  # Good pressure signal
elif pressure_ratio > 0.02:
    confidence_miles = segment_length * 0.15  # Moderate signal
else:
    confidence_miles = segment_length * 0.25  # Weak signal, low confidence

# Calculate mile marker range
mm_low = round(estimated_mile_marker - confidence_miles, 1)
mm_high = round(estimated_mile_marker + confidence_miles, 1)

result = {{
    "upstream_station": upstream_station,
    "downstream_station": downstream_station,
    "estimated_mile_marker": round(estimated_mile_marker, 1),
    "mile_marker_range": [mm_low, mm_high],
    "confidence_miles": round(confidence_miles, 1),
    "pressure_gradient_psi_per_mile": round(normal_gradient, 3),
    "elevation_correction_psi": round(elevation_pressure_correction, 3),
    "fractional_position": round(fractional_position, 3)
}}
print(json.dumps(result))
"""
    return {
        "code": code,
        "description": "Leak location estimation using pressure gradient analysis. Execute this code in the Code Interpreter to get the estimated mile marker range.",
    }



@tool
def calculate_line_pack_correction(
    temperature_delta_f: float,
    segment_length_miles: float,
    diameter_in: float,
    operating_pressure_psi: float,
    compressibility_factor: float,
    specific_gravity: float,
) -> dict:
    """Calculate the expected line pack change due to ambient temperature variation.

    Line pack is the volume of gas stored in the pipeline at operating conditions.
    Temperature changes cause gas density changes, which alter line pack without any
    gas actually entering or leaving the system. This must be subtracted from the
    mass balance to avoid false positive leak detections during temperature swings.

    Args:
        temperature_delta_f: Change in ambient temperature in Fahrenheit (negative = cooling).
        segment_length_miles: Length of the pipeline segment in miles.
        diameter_in: Pipeline internal diameter in inches.
        operating_pressure_psi: Current average operating pressure in PSI.
        compressibility_factor: Gas compressibility factor Z.
        specific_gravity: Gas specific gravity relative to air.
    """
    code = f"""
import json
import math

# Input parameters
temp_delta_f = {temperature_delta_f}  # Temperature change (°F), negative = cooling
segment_length = {segment_length_miles}  # miles
diameter = {diameter_in}  # inches
pressure = {operating_pressure_psi}  # PSI operating pressure
z_factor = {compressibility_factor}
sg = {specific_gravity}

# Calculate pipeline volume
# Convert segment length to feet, then calculate cylindrical volume
segment_length_ft = segment_length * 5280  # miles to feet
radius_ft = (diameter / 2.0) / 12.0  # inches to feet
pipe_volume_ft3 = math.pi * radius_ft**2 * segment_length_ft

# Convert to standard cubic feet using real gas law
# PV = nZRT → n = PV/(ZRT)
# At standard conditions: P_std = 14.696 psia, T_std = 519.67°R (60°F)
p_std = 14.696  # psia
t_std = 519.67  # °R (60°F standard)

# Assume current gas temperature is the pipeline soil temperature (~55°F typical)
# The temperature delta affects the gas temperature over time
base_gas_temp_f = 55.0
t_gas_before = base_gas_temp_f + 459.67  # Rankine before temp change
t_gas_after = (base_gas_temp_f + temp_delta_f) + 459.67  # Rankine after

# Line pack at current conditions (before temperature change)
# Standard volume = (P_line / P_std) * (T_std / T_gas) * (1/Z) * V_pipe
line_pack_before_scf = (pressure / p_std) * (t_std / t_gas_before) * (1.0 / z_factor) * pipe_volume_ft3

# Line pack after temperature change
line_pack_after_scf = (pressure / p_std) * (t_std / t_gas_after) * (1.0 / z_factor) * pipe_volume_ft3

# Change in line pack (positive = gas appears to accumulate, negative = gas appears to leave)
line_pack_change_scf = line_pack_after_scf - line_pack_before_scf
line_pack_change_mmscf = line_pack_change_scf / 1_000_000.0

# Convert to equivalent flow rate assuming the change happens over ~1 hour
# This gives the apparent flow imbalance that temperature change creates
equivalent_flow_rate_mmscfd = line_pack_change_mmscf * 24.0  # Scale hourly to daily

result = {{
    "line_pack_change_mmscf": round(line_pack_change_mmscf, 4),
    "equivalent_flow_rate_mmscfd": round(equivalent_flow_rate_mmscfd, 4),
    "pipe_volume_ft3": round(pipe_volume_ft3, 1),
    "line_pack_before_mmscf": round(line_pack_before_scf / 1_000_000, 4),
    "line_pack_after_mmscf": round(line_pack_after_scf / 1_000_000, 4),
    "interpretation": "significant_correction" if abs(equivalent_flow_rate_mmscfd) > 0.1 else "minor_correction"
}}
print(json.dumps(result))
"""
    return {
        "code": code,
        "description": "Line pack correction calculation for temperature effects. Execute this code in the Code Interpreter to determine how much of the observed deficit is due to temperature change.",
    }



@tool
def estimate_leak_rate(
    mass_balance_deficit_mmscfd: float,
    compressibility_factor: float,
    temperature_f: float,
    pressure_psi: float,
) -> dict:
    """Estimate the leak rate in MMSCFD from the corrected mass balance deficit.

    Converts the observed mass balance deficit (already corrected for temperature
    and operational transients) into a standardized leak rate at base conditions.
    This accounts for the difference between actual flowing conditions and standard
    reporting conditions.

    Args:
        mass_balance_deficit_mmscfd: The corrected mass balance deficit in MMSCFD (after all corrections applied).
        compressibility_factor: Gas compressibility factor Z at flowing conditions.
        temperature_f: Gas temperature at flowing conditions in Fahrenheit.
        pressure_psi: Average line pressure in PSI at the leak segment.
    """
    code = f"""
import json

# Input parameters
deficit = {mass_balance_deficit_mmscfd}  # Corrected deficit in MMSCFD
z_factor = {compressibility_factor}
temperature_f = {temperature_f}
pressure_psi = {pressure_psi}

# Standard conditions for reporting
p_std = 14.696  # psia
t_std = 519.67  # °R (60°F)

# Convert flowing conditions to Rankine
t_flowing = temperature_f + 459.67

# The deficit is already in MMSCFD at measurement conditions.
# Apply a small correction to normalize to standard reporting conditions.
# Flow at standard = Flow at actual * (P_actual/P_std) * (T_std/T_actual) * (1/Z)
# But since SCADA typically already reports at standard conditions, the correction is minor.
# We apply it as a refinement factor.
correction_factor = (t_std / t_flowing) * (1.0 / z_factor)

# Estimated leak rate at standard conditions
leak_rate_mmscfd = deficit * correction_factor

# Cumulative gas loss estimate (assuming leak has been active for the measurement window)
# For PHMSA reporting: need cumulative loss in MMSCF
# Assume leak detected within 30 minutes of onset
estimated_duration_hours = 0.5
cumulative_loss_mmscf = leak_rate_mmscfd * (estimated_duration_hours / 24.0)

# Project 24-hour loss if not isolated
projected_24hr_loss_mmscf = leak_rate_mmscfd * 1.0  # 1 day at current rate

# PHMSA threshold check: 3 MMSCF cumulative triggers mandatory reporting
phmsa_threshold_mmscf = 3.0
hours_to_threshold = (phmsa_threshold_mmscf / leak_rate_mmscfd) * 24.0 if leak_rate_mmscfd > 0 else float('inf')

result = {{
    "leak_rate_mmscfd": round(leak_rate_mmscfd, 4),
    "correction_factor": round(correction_factor, 6),
    "cumulative_loss_mmscf": round(cumulative_loss_mmscf, 4),
    "projected_24hr_loss_mmscf": round(projected_24hr_loss_mmscf, 4),
    "hours_to_phmsa_threshold": round(hours_to_threshold, 1),
    "phmsa_reportable_now": cumulative_loss_mmscf >= phmsa_threshold_mmscf
}}
print(json.dumps(result))
"""
    return {
        "code": code,
        "description": "Leak rate estimation from corrected mass balance deficit. Execute this code in the Code Interpreter to get the standardized leak rate and PHMSA threshold analysis.",
    }


@tool
def classify_severity(leak_rate_mmscfd: float) -> dict:
    """Classify leak severity based on the estimated leak rate.

    Uses industry-standard thresholds to categorize the leak into one of four
    severity levels. Each level maps to different response urgency and regulatory
    reporting requirements.

    Args:
        leak_rate_mmscfd: Estimated leak rate in MMSCFD (million standard cubic feet per day).
    """
    # This classification is simple enough to compute directly without Code Interpreter,
    # but we keep it as a tool so the agent's reasoning chain is explicit and auditable.
    if leak_rate_mmscfd < 0.25:
        severity = "seep"
        description = "Minor seepage, monitor closely"
        response_urgency = "routine"
        isolation_required = False
    elif leak_rate_mmscfd < 0.75:
        severity = "moderate"
        description = "Moderate leak requiring prompt attention"
        response_urgency = "elevated"
        isolation_required = True
    elif leak_rate_mmscfd < 1.5:
        severity = "significant"
        description = "Significant leak requiring immediate isolation"
        response_urgency = "urgent"
        isolation_required = True
    else:
        severity = "near_rupture"
        description = "Near-rupture conditions, emergency shutdown required"
        response_urgency = "emergency"
        isolation_required = True

    # PHMSA reporting thresholds (49 CFR 191.5)
    # Immediate NRC notification required if cumulative loss >= 3 MMSCF
    # or if the release is uncontrolled and causes fire/explosion
    phmsa_reportable = leak_rate_mmscfd >= 0.75  # At this rate, 3 MMSCF reached in ~4 days

    return {
        "severity": severity,
        "leak_rate_mmscfd": round(leak_rate_mmscfd, 4),
        "description": description,
        "response_urgency": response_urgency,
        "isolation_required": isolation_required,
        "phmsa_reportable": phmsa_reportable,
        "nrc_notification_required": severity in ("significant", "near_rupture"),
    }



# --- Memory Integration Tools ---
# These tools interact with AgentCore Long-Term Memory (LTM) to store and
# retrieve operational baselines and event signatures for improved disambiguation.

import json
import logging
import os

from bedrock_agentcore.memory import MemoryClient

logger = logging.getLogger(__name__)

# Memory configuration — the memory_id is set at deployment time via environment variable
_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
_MEMORY_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

# Namespace patterns for organizing memory records
_BASELINES_NAMESPACE = "/pipeline/baselines/"
_INCIDENTS_NAMESPACE = "/pipeline/incidents/"


def _get_memory_client() -> MemoryClient:
    """Lazily initialize the MemoryClient to avoid import-time AWS calls."""
    return MemoryClient(region_name=_MEMORY_REGION)


@tool
def get_operational_baseline(station_id: str) -> dict:
    """Retrieve the operational baseline for a specific station from AgentCore long-term memory.

    Returns the learned normal operating ranges (pressure, flow, line pack) for the
    given station. These baselines are used to compare against current readings to
    determine if a deviation is truly anomalous or within normal operational variation.

    Args:
        station_id: The station identifier (e.g., "ST-05") to retrieve baselines for.
    """
    try:
        client = _get_memory_client()

        # Search LTM for baseline records matching this station
        memories = client.retrieve_memories(
            memory_id=_MEMORY_ID,
            namespace=_BASELINES_NAMESPACE,
            query=f"operational baseline for station {station_id} normal pressure flow range",
            top_k=3,
        )

        if memories:
            # Return the most relevant baseline record
            baselines = []
            for record in memories:
                content = record.get("content", {}).get("text", "")
                baselines.append(content)

            return {
                "station_id": station_id,
                "baselines_found": True,
                "records": baselines,
                "source": "agentcore_ltm",
            }
        else:
            # No learned baselines yet — return hardcoded defaults from pipeline specs
            # These are the fallback values from the operating procedures
            default_baselines = {
                "ST-01": {"pressure_range": [760, 800], "flow_range": [6.0, 6.5], "line_pack_mmscf": 12.5},
                "ST-02": {"pressure_range": [745, 785], "flow_range": [5.9, 6.4], "line_pack_mmscf": 11.8},
                "ST-03": {"pressure_range": [735, 775], "flow_range": [5.9, 6.4], "line_pack_mmscf": 11.2},
                "ST-04": {"pressure_range": [755, 795], "flow_range": [5.9, 6.4], "line_pack_mmscf": 12.0},
                "ST-05": {"pressure_range": [740, 780], "flow_range": [5.8, 6.3], "line_pack_mmscf": 11.5},
                "ST-06": {"pressure_range": [730, 770], "flow_range": [5.8, 6.3], "line_pack_mmscf": 11.0},
                "ST-07": {"pressure_range": [720, 760], "flow_range": [5.7, 6.2], "line_pack_mmscf": 10.5},
                "ST-08": {"pressure_range": [710, 750], "flow_range": [5.7, 6.2], "line_pack_mmscf": 10.0},
            }

            baseline = default_baselines.get(station_id, {})
            return {
                "station_id": station_id,
                "baselines_found": False,
                "records": [json.dumps(baseline)] if baseline else [],
                "source": "hardcoded_defaults",
                "note": "No learned baselines in LTM yet. Using operating procedure defaults.",
            }

    except Exception as e:
        logger.warning("Failed to retrieve baseline from LTM for %s: %s", station_id, e)
        return {
            "station_id": station_id,
            "baselines_found": False,
            "records": [],
            "source": "error",
            "error": str(e),
        }


@tool
def store_event_signature(
    event_type: str,
    station_id: str,
    signature_description: str,
    classification: str,
    key_indicators: str,
) -> dict:
    """Store a confirmed event signature in AgentCore long-term memory for future disambiguation.

    After the agent confirms whether an event is a real leak or a false positive, it stores
    the event's signature so that similar future events can be classified more quickly and
    accurately. This is how the agent "learns" over time.

    Args:
        event_type: Type of event (e.g., "compressor_start", "valve_change", "temperature_shift", "real_leak").
        station_id: The station where the event was observed (e.g., "ST-05").
        signature_description: Human-readable description of the event signature and how it was classified.
        classification: Final classification of the event ("false_positive" or "real_leak").
        key_indicators: JSON string of the key indicator values that characterized this event.
    """
    try:
        client = _get_memory_client()

        # Compose the memory content as a structured text record
        memory_content = (
            f"Event signature for {station_id}: "
            f"Type={event_type}, Classification={classification}. "
            f"{signature_description} "
            f"Key indicators: {key_indicators}"
        )

        # Store as a conversation event that the semantic strategy will extract into LTM
        event = client.create_event(
            memory_id=_MEMORY_ID,
            actor_id="pipeline-integrity-agent",
            session_id=f"signature-{station_id}-{event_type}",
            messages=[
                (memory_content, "ASSISTANT"),
            ],
        )

        return {
            "stored": True,
            "event_type": event_type,
            "station_id": station_id,
            "classification": classification,
            "event_id": event.get("eventId", "unknown"),
            "note": "Signature stored in LTM. Will be available for future disambiguation.",
        }

    except Exception as e:
        logger.warning("Failed to store event signature in LTM: %s", e)
        return {
            "stored": False,
            "event_type": event_type,
            "station_id": station_id,
            "error": str(e),
            "note": "Memory service unavailable. Agent will continue without storing this signature.",
        }
