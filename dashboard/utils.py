"""Data utility functions for the Pipeline Integrity Dashboard.

Provides helper functions to read pipeline data from DynamoDB and S3.
All functions use boto3 directly with the SageMaker Studio execution role
credentials (no explicit credential management needed).

Environment variables:
    SCADA_BUCKET: S3 bucket name for SCADA data
    SEGMENTS_TABLE: DynamoDB table for pipeline segments
    VALVE_TABLE: DynamoDB table for valve status
    INCIDENTS_TABLE: DynamoDB table for incidents
    AWS_DEFAULT_REGION: AWS region (default: us-west-2)
"""

import os
from io import StringIO
from typing import Optional

import boto3
import pandas as pd

# --- Configuration from environment ---
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
SCADA_BUCKET = os.environ.get("SCADA_BUCKET", "pipeline-integrity-agent-data-211125430374-dev")
SEGMENTS_TABLE = os.environ.get("SEGMENTS_TABLE", "pipeline-integrity-agent-PipelineSegments-dev")
VALVE_TABLE = os.environ.get("VALVE_TABLE", "pipeline-integrity-agent-ValveStatus-dev")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "pipeline-integrity-agent-Incidents-dev")
SCADA_S3_KEY = os.environ.get("SCADA_S3_KEY", "scada/scada_timeseries.csv")

# --- Boto3 clients (initialized once, reused across calls) ---
_s3_client: Optional[boto3.client] = None
_dynamodb_resource: Optional[boto3.resource] = None


def _get_s3_client():
    """Lazily initialize S3 client to avoid import-time AWS calls."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=AWS_REGION)
    return _s3_client


def _get_dynamodb():
    """Lazily initialize DynamoDB resource."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb_resource


def get_latest_scada_readings(num_rows: int = 100) -> pd.DataFrame:
    """Fetch the most recent SCADA readings from S3.

    Reads the SCADA timeseries CSV from S3 and returns the last N rows
    (most recent readings across all stations).

    Args:
        num_rows: Number of most recent rows to return (default 100).

    Returns:
        DataFrame with SCADA readings sorted by timestamp descending.
    """
    try:
        s3 = _get_s3_client()
        # Try live readings first (written by simulate_live_scada.py)
        try:
            response = s3.get_object(Bucket=SCADA_BUCKET, Key="scada/live_readings.csv")
            csv_content = response["Body"].read().decode("utf-8")
            df = pd.read_csv(StringIO(csv_content))
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp", ascending=False)
            return df.head(num_rows)
        except Exception:
            pass

        # Fall back to full SCADA CSV
        response = s3.get_object(Bucket=SCADA_BUCKET, Key=SCADA_S3_KEY)
        csv_content = response["Body"].read().decode("utf-8")
        df = pd.read_csv(StringIO(csv_content))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp", ascending=False)
        return df.head(num_rows)
    except Exception:
        # Fallback: try reading from local data/ directory (for local dev)
        return _read_local_scada(num_rows)


def get_scada_history(
    station_ids: Optional[list[str]] = None,
    hours: int = 24,
) -> pd.DataFrame:
    """Fetch SCADA history for specified stations over a time window.

    Args:
        station_ids: List of station IDs to filter (None = all stations).
        hours: Number of hours of history to return.

    Returns:
        DataFrame with SCADA readings filtered by station and time.
    """
    try:
        s3 = _get_s3_client()
        response = s3.get_object(Bucket=SCADA_BUCKET, Key=SCADA_S3_KEY)
        csv_content = response["Body"].read().decode("utf-8")
        df = pd.read_csv(StringIO(csv_content))
    except Exception:
        df = _read_local_scada_full()

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Filter by time window
    max_time = df["timestamp"].max()
    cutoff = max_time - pd.Timedelta(hours=hours)
    df = df[df["timestamp"] >= cutoff]

    # Filter by station if specified
    if station_ids:
        df = df[df["station_id"].isin(station_ids)]

    return df.sort_values("timestamp", ascending=True)


def get_incidents() -> list[dict]:
    """Fetch all incidents from DynamoDB Incidents table.

    Returns:
        List of incident dicts sorted by timestamp descending.
    """
    try:
        dynamodb = _get_dynamodb()
        table = dynamodb.Table(INCIDENTS_TABLE)
        response = table.scan()
        items = response.get("Items", [])

        # Handle pagination for large tables
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        # Sort by timestamp descending (most recent first)
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items
    except Exception:
        # Return empty list if table doesn't exist yet
        return []


def get_pipeline_segments() -> list[dict]:
    """Fetch all pipeline segments from DynamoDB.

    Returns:
        List of segment dicts with geometry and valve info.
    """
    try:
        dynamodb = _get_dynamodb()
        table = dynamodb.Table(SEGMENTS_TABLE)
        response = table.scan()
        items = response.get("Items", [])

        # Sort by segment_id for consistent ordering
        items.sort(key=lambda x: x.get("segment_id", ""))
        return items
    except Exception:
        # Fallback: read from local CSV
        return _read_local_segments()


def get_valve_status() -> list[dict]:
    """Fetch current valve status from DynamoDB.

    Returns:
        List of valve status dicts with position and test results.
    """
    try:
        dynamodb = _get_dynamodb()
        table = dynamodb.Table(VALVE_TABLE)
        response = table.scan()
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("valve_id", ""))
        return items
    except Exception:
        return []


# --- Local fallback functions (for development without AWS) ---


def _read_local_scada(num_rows: int) -> pd.DataFrame:
    """Read SCADA data from local data/ directory as fallback."""
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "scada_timeseries.csv"
    )
    if os.path.exists(local_path):
        df = pd.read_csv(local_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp", ascending=False)
        return df.head(num_rows)
    return pd.DataFrame()


def _read_local_scada_full() -> pd.DataFrame:
    """Read full SCADA data from local data/ directory."""
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "scada_timeseries.csv"
    )
    if os.path.exists(local_path):
        return pd.read_csv(local_path)
    return pd.DataFrame()


def _read_local_segments() -> list[dict]:
    """Read pipeline segments from local CSV as fallback."""
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "pipeline_segment_metadata.csv"
    )
    if os.path.exists(local_path):
        df = pd.read_csv(local_path)
        return df.to_dict("records")
    return []
