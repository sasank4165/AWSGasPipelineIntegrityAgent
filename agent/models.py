"""Data models for the Pipeline Integrity Agent.

Defines the core domain objects used throughout the agent's reasoning pipeline:
anomaly events, SCADA readings, pipeline segments, incident reports, and
operational baselines stored in long-term memory.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnomalyEvent:
    """Represents an anomaly trigger event from the SCADA pre-processor.

    This is the input payload the agent receives when invoked — it describes
    what threshold was breached and which stations/segments are affected.
    """

    event_id: str  # Unique anomaly trigger ID
    timestamp: str  # ISO 8601 timestamp of the anomaly detection
    anomaly_type: str  # pressure_drop | mass_balance_deficit | flow_imbalance
    affected_stations: list[str]  # e.g. ["ST-05", "ST-06"]
    affected_segment: str  # e.g. "SEG-05"
    trigger_values: dict  # Key metrics that triggered the event
    severity: str  # warning | critical


@dataclass
class ScadaReading:
    """A single SCADA telemetry reading from one station at one point in time.

    Contains all sensor values the agent needs for false positive disambiguation
    and leak analysis — pressure, flow, temperature, compressor/valve state, etc.
    """

    timestamp: str
    station_id: str
    station_type: str  # compressor | meter | custody_transfer
    pressure_psi: float
    pressure_upstream_psi: float
    flow_mmscfd: float
    flow_direction: str  # inlet | outlet
    temperature_f: float
    compressor_status: str  # running | standby | shutdown
    compressor_speed_rpm: int
    valve_position_pct: float
    line_pack_mmscf: float
    mass_balance_deficit_mmscfd: float
    event_flag: str  # normal | compressor_start | valve_change | leak | false_positive


@dataclass
class PipelineSegment:
    """Physical metadata for a pipeline segment between two stations.

    Used by the leak localization algorithm to estimate mile marker position
    based on pressure gradients and segment geometry.
    """

    segment_id: str
    from_station: str
    to_station: str
    length_miles: float
    diameter_in: float
    wall_thickness_in: float
    material_grade: str
    max_operating_pressure_psi: float
    elevation_start_ft: float
    elevation_end_ft: float
    valve_locations_mile_markers: list[float] = field(default_factory=list)
    maop_psi: float = 0.0


@dataclass
class IncidentReport:
    """The structured output the agent produces after confirming a leak.

    Contains the full reasoning chain: anomaly analysis, false positive checks,
    localization, severity, and recommended response actions.
    """

    incident_id: str  # e.g. "INC-2026-0847"
    timestamp: str
    response_time_seconds: int
    anomaly_analysis: dict  # Pressure/flow readings and deviations
    false_positive_check: dict  # Compressor, valve, weather checks performed
    classification: str  # real_leak | false_positive
    leak_localization: Optional[dict] = None  # Segment, mile marker range, confidence
    severity: Optional[str] = None  # seep | moderate | significant | near_rupture
    leak_rate_mmscfd: Optional[float] = None
    phmsa_reportable: bool = False
    recommended_actions: list[str] = field(default_factory=list)
    draft_notification: Optional[str] = None  # Pre-filled PHMSA Form 7100.1 content
    status: str = "open"  # open | investigating | resolved


@dataclass
class StationBaseline:
    """Per-station operational baseline stored in AgentCore long-term memory.

    The agent compares live readings against these learned norms to detect
    deviations that may indicate a leak vs. normal operational variation.
    """

    station_id: str
    normal_pressure_range_psi: tuple[float, float]
    normal_flow_range_mmscfd: tuple[float, float]
    typical_line_pack_mmscf: float
    seasonal_adjustment: str  # winter | summer | transition
    last_updated: str
