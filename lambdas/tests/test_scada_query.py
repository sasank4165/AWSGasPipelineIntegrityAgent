"""Unit tests for the SCADA Query Lambda handler.

Tests cover:
- Routing to correct handler functions based on tool_name
- Filtering SCADA readings by station and time range
- Detecting compressor start events in a time window
- Detecting valve change events in a time window
- Station metadata retrieval from DynamoDB
- Error handling for missing parameters and unknown tool names
"""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# Sample SCADA CSV data representing a mix of normal, compressor_start, and valve_change events
SAMPLE_SCADA_CSV = """timestamp,station_id,station_type,pressure_psi,pressure_upstream_psi,flow_mmscfd,flow_direction,temperature_f,compressor_status,compressor_speed_rpm,valve_position_pct,line_pack_mmscf,mass_balance_deficit_mmscfd,event_flag
2025-12-01T08:00:00,ST-05,compressor,755.0,760.0,5.8,inlet,40.0,running,3550,85,6.4,0.01,normal
2025-12-01T08:15:00,ST-05,compressor,748.0,755.0,5.5,inlet,40.2,running,3550,85,6.3,0.35,normal
2025-12-01T08:30:00,ST-05,compressor,742.0,750.0,5.2,inlet,40.5,running,3600,85,6.2,0.55,compressor_start
2025-12-01T08:45:00,ST-06,meter,750.0,755.0,5.6,outlet,39.8,standby,0,80,6.35,0.02,valve_change
2025-12-01T09:00:00,ST-06,meter,752.0,756.0,5.7,outlet,39.5,standby,0,88,6.38,0.01,normal
2025-12-01T09:15:00,ST-07,meter,760.0,763.0,5.9,inlet,41.0,standby,0,90,6.5,0.0,normal
"""


@pytest.fixture(autouse=True)
def mock_s3():
    """Mock S3 client to return sample SCADA CSV data for all tests."""
    with patch("lambdas.scada_query.handler.s3_client") as mock_client:
        mock_body = MagicMock()
        mock_body.read.return_value = SAMPLE_SCADA_CSV.encode("utf-8")
        mock_client.get_object.return_value = {"Body": mock_body}
        yield mock_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource for station metadata queries."""
    with patch("lambdas.scada_query.handler.dynamodb") as mock_ddb:
        mock_table = MagicMock()
        mock_ddb.Table.return_value = mock_table
        yield mock_table


class TestLambdaHandlerRouting:
    """Tests for the main lambda_handler routing logic."""

    def test_routes_to_query_scada_readings(self, mock_s3):
        """Verify that tool_name 'query_scada_readings' routes correctly."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-05"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 200

    def test_unknown_tool_name_returns_400(self):
        """Verify that an unrecognized tool_name returns a 400 error."""
        from lambdas.scada_query.handler import lambda_handler

        event = {"tool_name": "nonexistent_tool", "parameters": {}}
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "Unknown tool_name" in body["error"]

    def test_missing_tool_name_returns_400(self):
        """Verify that a missing tool_name returns a 400 error."""
        from lambdas.scada_query.handler import lambda_handler

        event = {"parameters": {}}
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400


class TestQueryScadaReadings:
    """Tests for the query_scada_readings function."""

    def test_filters_by_station_id(self, mock_s3):
        """Verify readings are filtered to only the requested station(s)."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-05"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:30:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 3
        for reading in body["readings"]:
            assert reading["station_id"] == "ST-05"

    def test_filters_by_time_range(self, mock_s3):
        """Verify readings are filtered to the specified time window."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-05", "ST-06", "ST-07"],
                "start_time": "2025-12-01T08:30:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        # Should include ST-05 08:30, ST-06 08:45, ST-06 09:00
        assert body["count"] == 3

    def test_filters_by_multiple_stations(self, mock_s3):
        """Verify filtering works with multiple station IDs."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-06", "ST-07"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:30:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 3
        station_ids = {r["station_id"] for r in body["readings"]}
        assert station_ids == {"ST-06", "ST-07"}

    def test_respects_limit_parameter(self, mock_s3):
        """Verify the limit parameter caps the number of returned readings."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-05", "ST-06", "ST-07"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:30:00",
                "limit": 2,
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 2

    def test_returns_readings_sorted_descending(self, mock_s3):
        """Verify readings are returned most-recent-first."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-05"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        timestamps = [r["timestamp"] for r in body["readings"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_missing_required_params_returns_error(self, mock_s3):
        """Verify that missing required parameters return an error dict."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {"station_ids": ["ST-05"]},  # Missing start_time, end_time
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert "error" in body

    def test_no_matching_readings_returns_empty(self, mock_s3):
        """Verify empty result when no readings match the filter criteria."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "query_scada_readings",
            "parameters": {
                "station_ids": ["ST-99"],  # Non-existent station
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 0
        assert body["readings"] == []


class TestCheckCompressorEvents:
    """Tests for the check_compressor_events function."""

    def test_detects_compressor_start_events(self, mock_s3):
        """Verify compressor_start events are found in the time window."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "check_compressor_events",
            "parameters": {
                "station_ids": ["ST-05"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["has_events"] is True
        assert body["count"] == 1
        assert body["compressor_events"][0]["station_id"] == "ST-05"
        assert body["compressor_events"][0]["event_flag"] == "compressor_start"

    def test_no_compressor_events_returns_false(self, mock_s3):
        """Verify has_events is False when no compressor events exist."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "check_compressor_events",
            "parameters": {
                "station_ids": ["ST-06"],  # ST-06 has valve_change, not compressor_start
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:30:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["has_events"] is False
        assert body["count"] == 0

    def test_missing_params_returns_error(self, mock_s3):
        """Verify error when required parameters are missing."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "check_compressor_events",
            "parameters": {"station_ids": ["ST-05"]},
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert "error" in body


class TestCheckValveChanges:
    """Tests for the check_valve_changes function."""

    def test_detects_valve_change_events(self, mock_s3):
        """Verify valve_change events are found in the time window."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "check_valve_changes",
            "parameters": {
                "station_ids": ["ST-06"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["has_changes"] is True
        assert body["count"] == 1
        assert body["valve_changes"][0]["station_id"] == "ST-06"

    def test_no_valve_changes_returns_false(self, mock_s3):
        """Verify has_changes is False when no valve events exist."""
        from lambdas.scada_query.handler import lambda_handler

        event = {
            "tool_name": "check_valve_changes",
            "parameters": {
                "station_ids": ["ST-05"],
                "start_time": "2025-12-01T08:00:00",
                "end_time": "2025-12-01T09:00:00",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["has_changes"] is False
        assert body["count"] == 0


class TestQueryStationMetadata:
    """Tests for the query_station_metadata function."""

    def test_get_segment_by_id(self, mock_dynamodb):
        """Verify direct segment lookup by segment_id."""
        from lambdas.scada_query.handler import lambda_handler

        mock_dynamodb.get_item.return_value = {
            "Item": {
                "segment_id": "SEG-05",
                "from_station": "ST-05",
                "to_station": "ST-06",
                "length_miles": 28.5,
                "diameter_in": 24,
            }
        }

        event = {
            "tool_name": "query_station_metadata",
            "parameters": {"segment_id": "SEG-05"},
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 1
        assert body["segments"][0]["segment_id"] == "SEG-05"
        assert body["segments"][0]["from_station"] == "ST-05"

    def test_get_segments_by_station_id(self, mock_dynamodb):
        """Verify segment lookup by station_id finds connected segments."""
        from lambdas.scada_query.handler import lambda_handler

        mock_dynamodb.scan.return_value = {
            "Items": [
                {"segment_id": "SEG-04", "from_station": "ST-04", "to_station": "ST-05"},
                {"segment_id": "SEG-05", "from_station": "ST-05", "to_station": "ST-06"},
                {"segment_id": "SEG-06", "from_station": "ST-06", "to_station": "ST-07"},
            ]
        }

        event = {
            "tool_name": "query_station_metadata",
            "parameters": {"station_id": "ST-05"},
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        # ST-05 is in SEG-04 (as to_station) and SEG-05 (as from_station)
        assert body["count"] == 2
        segment_ids = {s["segment_id"] for s in body["segments"]}
        assert segment_ids == {"SEG-04", "SEG-05"}

    def test_get_all_segments(self, mock_dynamodb):
        """Verify all segments are returned when no filter is specified."""
        from lambdas.scada_query.handler import lambda_handler

        mock_dynamodb.scan.return_value = {
            "Items": [
                {"segment_id": "SEG-01", "from_station": "ST-01", "to_station": "ST-02"},
                {"segment_id": "SEG-02", "from_station": "ST-02", "to_station": "ST-03"},
            ]
        }

        event = {
            "tool_name": "query_station_metadata",
            "parameters": {},
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 2

    def test_segment_not_found_returns_empty(self, mock_dynamodb):
        """Verify empty result when segment_id doesn't exist."""
        from lambdas.scada_query.handler import lambda_handler

        mock_dynamodb.get_item.return_value = {}

        event = {
            "tool_name": "query_station_metadata",
            "parameters": {"segment_id": "SEG-99"},
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["count"] == 0
        assert body["segments"] == []
