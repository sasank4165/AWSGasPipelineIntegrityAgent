"""SCADA Query Lambda — reads SCADA telemetry from S3 and pipeline metadata from DynamoDB.

This Lambda is exposed via AgentCore Gateway as an MCP tool. The Pipeline Integrity
Agent calls it to fetch historical SCADA readings, check compressor events, detect
valve changes, and retrieve pipeline segment metadata during anomaly investigations.

Environment Variables:
    SCADA_BUCKET: S3 bucket containing SCADA CSV data
    SEGMENTS_TABLE: DynamoDB table with pipeline segment metadata
    VALVE_TABLE: DynamoDB table with valve status records
"""

import json
import os
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

import boto3
import pandas as pd

# AWS clients — initialized outside handler for connection reuse across invocations
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Environment configuration
SCADA_BUCKET = os.environ.get("SCADA_BUCKET", "")
SEGMENTS_TABLE = os.environ.get("SEGMENTS_TABLE", "")
VALVE_TABLE = os.environ.get("VALVE_TABLE", "")


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point — routes to the appropriate query function.

    The AgentCore Gateway invokes this Lambda with a 'tool_name' field indicating
    which operation the agent wants to perform. Each tool maps to a specific
    query function that returns filtered SCADA data or metadata.

    Args:
        event: Contains 'tool_name' and 'parameters' from the MCP tool call.
              OR just the tool arguments directly (Gateway Lambda target format).
        context: Lambda execution context (unused but required by AWS).

    Returns:
        dict with statusCode and JSON body containing query results.
    """
    # Log the raw event for debugging Gateway integration
    print(f"RAW_EVENT: {json.dumps(event, default=str)[:2000]}")

    # Gateway Lambda targets send arguments directly as the event body.
    # The tool_name is passed via a special header or must be inferred.
    # Support both explicit tool_name format and inference from parameters.
    tool_name = event.get("tool_name") or event.get("name", "")
    parameters = event.get("parameters") or event.get("arguments", {})

    # If parameters is a JSON string, parse it
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except json.JSONDecodeError:
            parameters = {}

    # If no explicit tool_name, infer from the event structure
    # (Gateway sends tool arguments directly as the event)
    if not tool_name:
        if "segment_id" in event or ("station_id" in event and "start_time" not in event):
            tool_name = "query_station_metadata"
            parameters = event
        elif "station_ids" in event and "start_time" in event:
            # Distinguish between SCADA readings, compressor events, and valve changes
            # by checking if the agent explicitly requested a specific check
            # Default to query_scada_readings since it's the most common
            tool_name = "query_scada_readings"
            parameters = event
        else:
            # Fallback: treat entire event as parameters for query_scada_readings
            tool_name = "query_scada_readings"
            parameters = event

    # Route to the correct handler based on which MCP tool the agent invoked
    handlers = {
        "query_scada_readings": query_scada_readings,
        "check_compressor_events": check_compressor_events,
        "check_valve_changes": check_valve_changes,
        "query_station_metadata": query_station_metadata,
    }

    handler_fn = handlers.get(tool_name)
    if not handler_fn:
        return _error_response(400, f"Unknown tool_name: {tool_name}")

    try:
        result = handler_fn(parameters)
        return _success_response(result)
    except Exception as e:
        return _error_response(500, f"Error executing {tool_name}: {str(e)}")


def query_scada_readings(params: dict) -> dict:
    """Fetch SCADA readings filtered by station(s) and time range.

    The agent uses this to pull recent telemetry for the affected stations
    during an anomaly investigation. Returns all sensor fields needed for
    false positive disambiguation and leak analysis.

    Args:
        params: Dictionary with keys:
            - station_ids (list[str]): Stations to query, e.g. ["ST-05", "ST-06"]
            - start_time (str): ISO 8601 start of time window
            - end_time (str): ISO 8601 end of time window
            - limit (int, optional): Max rows to return (default 500)

    Returns:
        dict with 'readings' list and 'count' of results.
    """
    station_ids: list[str] = params.get("station_ids", [])
    start_time: str = params.get("start_time", "")
    end_time: str = params.get("end_time", "")
    limit: int = params.get("limit", 500)

    if not station_ids or not start_time or not end_time:
        return {"error": "station_ids, start_time, and end_time are required"}

    # Load SCADA CSV from S3 — for the demo dataset (~21 MB) this fits in Lambda memory
    df = _load_scada_csv()

    # Filter by station IDs
    df = df[df["station_id"].isin(station_ids)]

    # Filter by time range using pandas datetime comparison
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    df = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)]

    # Sort by time descending so the agent sees most recent readings first
    df = df.sort_values("timestamp", ascending=False).head(limit)

    # Convert timestamps back to ISO strings for JSON serialization
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    readings = df.to_dict(orient="records")
    return {"readings": readings, "count": len(readings)}


def check_compressor_events(params: dict) -> dict:
    """Check for compressor start/stop events in a time window around the anomaly.

    The agent calls this during false positive disambiguation — a compressor start
    can cause transient pressure drops that mimic a leak signature. If a compressor
    event is found within the window, the agent factors it into its analysis.

    Args:
        params: Dictionary with keys:
            - station_ids (list[str]): Stations to check
            - start_time (str): ISO 8601 start (typically anomaly_time - 2 hours)
            - end_time (str): ISO 8601 end (typically anomaly_time)

    Returns:
        dict with 'compressor_events' list and 'has_events' boolean flag.
    """
    station_ids: list[str] = params.get("station_ids", [])
    start_time: str = params.get("start_time", "")
    end_time: str = params.get("end_time", "")

    if not station_ids or not start_time or not end_time:
        return {"error": "station_ids, start_time, and end_time are required"}

    df = _load_scada_csv()

    # Filter to the specified stations and time window
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)

    df = df[
        (df["station_id"].isin(station_ids))
        & (df["timestamp"] >= start_dt)
        & (df["timestamp"] <= end_dt)
    ]

    # Look for compressor_start events — these are flagged in the event_flag column
    # and also detectable by transitions in compressor_status from standby→running
    compressor_events = df[df["event_flag"] == "compressor_start"]

    # Convert to serializable format
    compressor_events = compressor_events.copy()
    compressor_events["timestamp"] = compressor_events["timestamp"].dt.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    events_list = compressor_events.to_dict(orient="records")

    return {
        "compressor_events": events_list,
        "has_events": len(events_list) > 0,
        "count": len(events_list),
    }


def check_valve_changes(params: dict) -> dict:
    """Check for valve position changes in a time window around the anomaly.

    Valve movements (opening/closing) cause transient pressure and flow changes
    that can trigger false anomaly alerts. The agent checks this to rule out
    valve-induced transients before confirming a leak.

    Args:
        params: Dictionary with keys:
            - station_ids (list[str]): Stations to check
            - start_time (str): ISO 8601 start (typically anomaly_time - 30 min)
            - end_time (str): ISO 8601 end (typically anomaly_time)

    Returns:
        dict with 'valve_changes' list and 'has_changes' boolean flag.
    """
    station_ids: list[str] = params.get("station_ids", [])
    start_time: str = params.get("start_time", "")
    end_time: str = params.get("end_time", "")

    if not station_ids or not start_time or not end_time:
        return {"error": "station_ids, start_time, and end_time are required"}

    df = _load_scada_csv()

    # Filter to the specified stations and time window
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)

    df = df[
        (df["station_id"].isin(station_ids))
        & (df["timestamp"] >= start_dt)
        & (df["timestamp"] <= end_dt)
    ]

    # Look for valve_change events flagged in the SCADA data
    valve_changes = df[df["event_flag"] == "valve_change"]

    # Convert to serializable format
    valve_changes = valve_changes.copy()
    valve_changes["timestamp"] = valve_changes["timestamp"].dt.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    events_list = valve_changes.to_dict(orient="records")

    return {
        "valve_changes": events_list,
        "has_changes": len(events_list) > 0,
        "count": len(events_list),
    }



def query_station_metadata(params: dict) -> dict:
    """Retrieve pipeline segment metadata from DynamoDB.

    Returns physical properties of pipeline segments — length, diameter, elevation,
    valve locations — which the agent needs for leak localization calculations
    (pressure gradient analysis requires knowing segment geometry).

    Args:
        params: Dictionary with keys:
            - segment_id (str, optional): Specific segment to retrieve
            - station_id (str, optional): Find segments connected to this station

    Returns:
        dict with 'segments' list containing segment metadata.
    """
    segment_id: str = params.get("segment_id", "")
    station_id: str = params.get("station_id", "")

    table = dynamodb.Table(SEGMENTS_TABLE)

    if segment_id:
        # Direct lookup by segment ID — O(1) DynamoDB GetItem
        response = table.get_item(Key={"segment_id": segment_id})
        item = response.get("Item")
        if item:
            return {"segments": [_convert_decimals(item)], "count": 1}
        return {"segments": [], "count": 0}

    if station_id:
        # Scan for segments where this station is either the from or to endpoint.
        # For the demo dataset (7 segments) a scan is acceptable; in production
        # you'd add a GSI on from_station and to_station.
        response = table.scan()
        items = response.get("Items", [])
        matching = [
            _convert_decimals(item)
            for item in items
            if item.get("from_station") == station_id
            or item.get("to_station") == station_id
        ]
        return {"segments": matching, "count": len(matching)}

    # No filter — return all segments (useful for the agent to understand full topology)
    response = table.scan()
    items = [_convert_decimals(item) for item in response.get("Items", [])]
    return {"segments": items, "count": len(items)}


# ============================================================
# Helper Functions
# ============================================================


def _load_scada_csv() -> pd.DataFrame:
    """Load the SCADA time-series CSV from S3 into a pandas DataFrame.

    For the hackathon demo, the full 90-day dataset (~21 MB) fits comfortably
    in Lambda's 512 MB memory allocation. In production, this would be replaced
    with Athena queries over partitioned Parquet files.

    Returns:
        DataFrame with all SCADA readings.
    """
    response = s3_client.get_object(
        Bucket=SCADA_BUCKET, Key="scada/scada_timeseries.csv"
    )
    csv_content = response["Body"].read().decode("utf-8")
    return pd.read_csv(StringIO(csv_content))


def _convert_decimals(item: dict) -> dict:
    """Convert DynamoDB Decimal types to Python floats for JSON serialization.

    DynamoDB returns numbers as Decimal objects which aren't JSON-serializable.
    This recursively converts them to standard Python numeric types.
    """
    from decimal import Decimal

    converted = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            # Use int if the value has no fractional part, otherwise float
            converted[key] = int(value) if value == int(value) else float(value)
        elif isinstance(value, list):
            converted[key] = [
                int(v) if isinstance(v, Decimal) and v == int(v)
                else float(v) if isinstance(v, Decimal)
                else v
                for v in value
            ]
        elif isinstance(value, dict):
            converted[key] = _convert_decimals(value)
        else:
            converted[key] = value
    return converted


def _success_response(body: dict) -> dict:
    """Format a successful Lambda response with proper status code and headers."""
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _error_response(status_code: int, message: str) -> dict:
    """Format an error Lambda response with status code and error message."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
