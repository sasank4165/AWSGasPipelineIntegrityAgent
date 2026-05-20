"""Unit tests for the Incident Management Lambda handler.

Tests cover:
- Routing to correct handler functions based on tool_name
- Incident creation with unique ID generation and DynamoDB write
- Alert publishing to SNS with structured message formatting
- Error handling for missing parameters and unknown tool names
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_dynamodb():
    """Mock DynamoDB resource for incident creation tests."""
    with patch("lambdas.incident_mgmt.handler.dynamodb") as mock_ddb:
        mock_table = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_table.put_item.return_value = {}
        yield mock_table


@pytest.fixture(autouse=True)
def mock_sns():
    """Mock SNS client for alert publishing tests."""
    with patch("lambdas.incident_mgmt.handler.sns_client") as mock_client:
        mock_client.publish.return_value = {"MessageId": "test-message-id-12345"}
        yield mock_client


class TestLambdaHandlerRouting:
    """Tests for the main lambda_handler routing logic."""

    def test_routes_to_create_incident(self):
        """Verify that tool_name 'create_incident' routes correctly."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "create_incident",
            "parameters": {
                "classification": "real_leak",
                "affected_segment": "SEG-05",
                "affected_stations": ["ST-05", "ST-06"],
                "anomaly_analysis": {"pressure_drop_psi": 12},
                "false_positive_check": {"compressor": False, "valve": False},
                "severity": "moderate",
                "leak_rate_mmscfd": 0.55,
                "phmsa_reportable": False,
                "recommended_actions": ["Close valve V-12"],
                "response_time_seconds": 180,
            },
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 200

    def test_routes_to_send_alert(self):
        """Verify that tool_name 'send_alert' routes correctly."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "significant",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Close valve V-12", "Dispatch crew"],
                "phmsa_reportable": True,
                "summary": "Confirmed leak on SEG-05",
            },
        }
        response = lambda_handler(event, None)
        assert response["statusCode"] == 200

    def test_unknown_tool_name_returns_400(self):
        """Verify that an unrecognized tool_name returns a 400 error."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {"tool_name": "unknown_tool", "parameters": {}}
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "Unknown tool_name" in body["error"]

    def test_missing_tool_name_returns_400(self):
        """Verify that a missing tool_name returns a 400 error."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {"parameters": {}}
        response = lambda_handler(event, None)
        assert response["statusCode"] == 400


class TestCreateIncident:
    """Tests for the create_incident function."""

    def test_creates_incident_with_unique_id(self, mock_dynamodb):
        """Verify incident is created with a properly formatted ID."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "create_incident",
            "parameters": {
                "classification": "real_leak",
                "affected_segment": "SEG-05",
                "affected_stations": ["ST-05", "ST-06"],
                "anomaly_analysis": {"pressure_drop_psi": 12},
                "false_positive_check": {"compressor": False},
                "severity": "moderate",
                "leak_rate_mmscfd": 0.55,
                "phmsa_reportable": False,
                "recommended_actions": ["Close valve V-12"],
                "response_time_seconds": 180,
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        # Verify incident ID format: INC-YYYY-NNNN
        assert body["incident_id"].startswith("INC-")
        parts = body["incident_id"].split("-")
        assert len(parts) == 3
        assert parts[1].isdigit() and len(parts[1]) == 4  # Year
        assert parts[2].isdigit() and len(parts[2]) == 4  # Sequence

    def test_incident_written_to_dynamodb(self, mock_dynamodb):
        """Verify the incident record is written to DynamoDB with correct fields."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "create_incident",
            "parameters": {
                "classification": "real_leak",
                "affected_segment": "SEG-05",
                "affected_stations": ["ST-05", "ST-06"],
                "anomaly_analysis": {"pressure_drop_psi": 12},
                "false_positive_check": {"compressor": False},
                "severity": "significant",
                "leak_rate_mmscfd": 1.2,
                "phmsa_reportable": True,
                "recommended_actions": ["Close valve V-12", "Notify NRC"],
                "response_time_seconds": 240,
            },
        }
        lambda_handler(event, None)

        # Verify DynamoDB put_item was called
        mock_dynamodb.put_item.assert_called_once()
        written_item = mock_dynamodb.put_item.call_args[1]["Item"]

        assert written_item["classification"] == "real_leak"
        assert written_item["affected_segment"] == "SEG-05"
        assert written_item["status"] == "open"
        assert "incident_id" in written_item
        assert "timestamp" in written_item

    def test_incident_status_is_open(self, mock_dynamodb):
        """Verify newly created incidents have status 'open'."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "create_incident",
            "parameters": {
                "classification": "false_positive",
                "affected_segment": "SEG-03",
                "affected_stations": ["ST-03"],
                "anomaly_analysis": {},
                "false_positive_check": {"compressor": True},
                "phmsa_reportable": False,
                "recommended_actions": [],
                "response_time_seconds": 60,
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["status"] == "open"

    def test_none_fields_excluded_from_dynamodb(self, mock_dynamodb):
        """Verify None values are not written to DynamoDB (it doesn't support them)."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "create_incident",
            "parameters": {
                "classification": "false_positive",
                "affected_segment": "SEG-03",
                "affected_stations": ["ST-03"],
                "anomaly_analysis": {},
                "false_positive_check": {"compressor": True},
                # These optional fields will be None
                # leak_localization, severity, leak_rate_mmscfd, draft_notification
                "phmsa_reportable": False,
                "recommended_actions": [],
                "response_time_seconds": 45,
            },
        }
        lambda_handler(event, None)

        written_item = mock_dynamodb.put_item.call_args[1]["Item"]
        # None values should be excluded from the DynamoDB item
        for value in written_item.values():
            assert value is not None


class TestSendAlert:
    """Tests for the send_alert function."""

    def test_publishes_to_sns_topic(self, mock_sns):
        """Verify alert is published to the configured SNS topic."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "significant",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Close valve V-12"],
                "phmsa_reportable": True,
                "summary": "Confirmed leak on SEG-05",
            },
        }
        response = lambda_handler(event, None)
        body = json.loads(response["body"])

        assert body["message_id"] == "test-message-id-12345"
        mock_sns.publish.assert_called_once()

    def test_alert_includes_severity_in_subject(self, mock_sns):
        """Verify the SNS subject line includes the severity level."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "near_rupture",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Emergency shutdown"],
                "phmsa_reportable": True,
                "summary": "Critical leak detected",
            },
        }
        lambda_handler(event, None)

        call_kwargs = mock_sns.publish.call_args[1]
        assert "NEAR_RUPTURE" in call_kwargs["Subject"]
        assert "INC-2026-0501" in call_kwargs["Subject"]

    def test_alert_message_contains_key_fields(self, mock_sns):
        """Verify the alert message body contains all critical information."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "moderate",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Close valve V-12", "Dispatch crew"],
                "phmsa_reportable": False,
                "summary": "Moderate leak confirmed on segment 5",
            },
        }
        lambda_handler(event, None)

        call_kwargs = mock_sns.publish.call_args[1]
        message = call_kwargs["Message"]

        assert "INC-2026-0501" in message
        assert "MODERATE" in message
        assert "SEG-05" in message
        assert "Mile marker 112-118" in message
        assert "Close valve V-12" in message

    def test_phmsa_reportable_flag_in_message_attributes(self, mock_sns):
        """Verify PHMSA reportable flag is included as a message attribute for filtering."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "significant",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Notify NRC"],
                "phmsa_reportable": True,
                "summary": "PHMSA reportable leak",
            },
        }
        lambda_handler(event, None)

        call_kwargs = mock_sns.publish.call_args[1]
        attrs = call_kwargs["MessageAttributes"]
        assert attrs["phmsa_reportable"]["StringValue"] == "True"
        assert attrs["severity"]["StringValue"] == "significant"

    def test_phmsa_notice_included_when_reportable(self, mock_sns):
        """Verify PHMSA warning notice appears in message when reportable."""
        from lambdas.incident_mgmt.handler import lambda_handler

        event = {
            "tool_name": "send_alert",
            "parameters": {
                "incident_id": "INC-2026-0501",
                "severity": "significant",
                "affected_segment": "SEG-05",
                "leak_location": "Mile marker 112-118",
                "recommended_actions": ["Notify NRC"],
                "phmsa_reportable": True,
                "summary": "Reportable leak",
            },
        }
        lambda_handler(event, None)

        call_kwargs = mock_sns.publish.call_args[1]
        message = call_kwargs["Message"]
        assert "PHMSA REPORTABLE" in message


class TestIncidentIdGeneration:
    """Tests for the _generate_incident_id helper."""

    def test_id_format(self):
        """Verify the incident ID follows the INC-YYYY-NNNN format."""
        from lambdas.incident_mgmt.handler import _generate_incident_id

        test_time = datetime(2026, 5, 20, 14, 30, 0, tzinfo=timezone.utc)
        incident_id = _generate_incident_id(test_time)

        assert incident_id.startswith("INC-2026-")
        parts = incident_id.split("-")
        assert len(parts) == 3
        assert len(parts[2]) == 4  # Zero-padded sequence

    def test_different_times_produce_different_ids(self):
        """Verify different timestamps produce different incident IDs."""
        from lambdas.incident_mgmt.handler import _generate_incident_id

        time1 = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
        time2 = datetime(2026, 5, 21, 10, 0, 0, tzinfo=timezone.utc)

        id1 = _generate_incident_id(time1)
        id2 = _generate_incident_id(time2)

        assert id1 != id2
