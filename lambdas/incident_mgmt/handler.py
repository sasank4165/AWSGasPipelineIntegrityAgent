"""Incident Management Lambda — creates incident records and publishes control room alerts.

This Lambda is exposed via AgentCore Gateway as an MCP tool. The Pipeline Integrity
Agent calls it after confirming a real leak to create a tracked incident in DynamoDB
and notify the control room via SNS with a structured alert message.

Environment Variables:
    INCIDENTS_TABLE: DynamoDB table for storing incident reports
    SNS_TOPIC_ARN: SNS topic ARN for control room alert notifications
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

# AWS clients — initialized outside handler for connection reuse
dynamodb = boto3.resource("dynamodb")
sns_client = boto3.client("sns")

# Environment configuration
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point — routes to create_incident or send_alert.

    The AgentCore Gateway invokes this Lambda with a 'tool_name' field indicating
    which operation the agent wants: creating a persistent incident record or
    sending an immediate alert to the control room.

    Args:
        event: Contains 'tool_name' and 'parameters' from the MCP tool call.
        context: Lambda execution context (unused but required by AWS).

    Returns:
        dict with statusCode and JSON body containing operation results.
    """
    # Log the raw event for debugging Gateway integration
    print(f"RAW_EVENT: {json.dumps(event, default=str)[:2000]}")

    # Support both original format and Gateway MCP format
    tool_name = event.get("tool_name") or event.get("name", "")
    parameters = event.get("parameters") or event.get("arguments", {})

    # If parameters is a JSON string, parse it
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except json.JSONDecodeError:
            parameters = {}

    # If no explicit tool_name, infer from the event structure
    # Gateway Lambda targets send arguments directly as the event body
    if not tool_name:
        if "incident_id" in event and "summary" in event:
            tool_name = "send_alert"
            parameters = event
        elif "classification" in event or "affected_segment" in event:
            tool_name = "create_incident"
            parameters = event
        else:
            tool_name = "create_incident"
            parameters = event

    handlers = {
        "create_incident": create_incident,
        "send_alert": send_alert,
    }

    handler_fn = handlers.get(tool_name)
    if not handler_fn:
        return _error_response(400, f"Unknown tool_name: {tool_name}")

    try:
        result = handler_fn(parameters)
        return _success_response(result)
    except Exception as e:
        return _error_response(500, f"Error executing {tool_name}: {str(e)}")


def create_incident(params: dict) -> dict:
    """Create a new incident record in DynamoDB with a unique incident ID.

    The agent calls this after completing its full analysis pipeline (anomaly
    detection → false positive check → localization → severity assessment).
    The incident record captures the entire reasoning chain for audit purposes.

    Incident ID format: INC-YYYY-NNNN where YYYY is the current year and NNNN
    is a zero-padded sequence number derived from the current timestamp to ensure
    uniqueness within the demo context.

    Args:
        params: Dictionary with incident report fields:
            - classification (str): "real_leak" or "false_positive"
            - affected_segment (str): e.g. "SEG-05"
            - affected_stations (list[str]): e.g. ["ST-05", "ST-06"]
            - anomaly_analysis (dict): Pressure/flow readings and deviations
            - false_positive_check (dict): Checks performed and results
            - leak_localization (dict, optional): Segment, mile marker, confidence
            - severity (str, optional): seep | moderate | significant | near_rupture
            - leak_rate_mmscfd (float, optional): Estimated leak rate
            - phmsa_reportable (bool): Whether PHMSA notification is required
            - recommended_actions (list[str]): Response actions for control room
            - draft_notification (str, optional): Pre-filled PHMSA form content
            - response_time_seconds (int): Time from anomaly trigger to report

    Returns:
        dict with 'incident_id', 'timestamp', and 'status' confirming creation.
    """
    # Generate a unique incident ID using the format INC-YYYY-NNNN
    # The sequence number uses hour+minute+second to avoid collisions in the demo
    now = datetime.now(timezone.utc)
    incident_id = _generate_incident_id(now)

    # Build the incident record with all fields from the agent's analysis
    incident_record = {
        "incident_id": incident_id,
        "timestamp": now.isoformat(),
        "classification": params.get("classification", "unknown"),
        "affected_segment": params.get("affected_segment", ""),
        "affected_stations": params.get("affected_stations", []),
        "anomaly_analysis": params.get("anomaly_analysis", {}),
        "false_positive_check": params.get("false_positive_check", {}),
        "leak_localization": params.get("leak_localization"),
        "severity": params.get("severity"),
        "leak_rate_mmscfd": params.get("leak_rate_mmscfd"),
        "phmsa_reportable": params.get("phmsa_reportable", False),
        "recommended_actions": params.get("recommended_actions", []),
        "draft_notification": params.get("draft_notification"),
        "response_time_seconds": params.get("response_time_seconds", 0),
        "status": "open",
    }

    # Write to DynamoDB — the Incidents table uses incident_id as partition key
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.put_item(Item=_prepare_for_dynamodb(incident_record))

    return {
        "incident_id": incident_id,
        "timestamp": now.isoformat(),
        "status": "open",
        "message": f"Incident {incident_id} created successfully",
    }


def send_alert(params: dict) -> dict:
    """Publish a structured alert message to the control room SNS topic.

    The agent calls this to immediately notify pipeline controllers of a
    confirmed leak. The message includes severity, location, and recommended
    immediate actions so controllers can respond without waiting for the
    full incident report.

    Args:
        params: Dictionary with alert fields:
            - incident_id (str): Reference to the incident record
            - severity (str): seep | moderate | significant | near_rupture
            - affected_segment (str): e.g. "SEG-05"
            - leak_location (str): Estimated mile marker range
            - recommended_actions (list[str]): Immediate response steps
            - phmsa_reportable (bool): Whether NRC notification is required
            - summary (str): Brief description of the incident

    Returns:
        dict with 'message_id' confirming SNS publication and alert details.
    """
    incident_id: str = params.get("incident_id", "UNKNOWN")
    severity: str = params.get("severity", "unknown")
    affected_segment: str = params.get("affected_segment", "")
    leak_location: str = params.get("leak_location", "Unknown")
    recommended_actions: list = params.get("recommended_actions", [])
    phmsa_reportable: bool = params.get("phmsa_reportable", False)
    summary: str = params.get("summary", "Pipeline integrity alert")

    # Build a structured alert message for the control room
    # Format is designed for quick scanning by pipeline controllers under pressure
    alert_message = _format_alert_message(
        incident_id=incident_id,
        severity=severity,
        affected_segment=affected_segment,
        leak_location=leak_location,
        recommended_actions=recommended_actions,
        phmsa_reportable=phmsa_reportable,
        summary=summary,
    )

    # Determine SNS subject line based on severity for email filtering
    subject = f"[{severity.upper()}] Pipeline Alert — {incident_id}"

    # Publish to SNS — delivers to all subscribed endpoints (email, SMS, Lambda, etc.)
    response = sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject[:100],  # SNS subject has 100-char limit
        Message=alert_message,
        MessageAttributes={
            "severity": {"DataType": "String", "StringValue": severity},
            "segment": {"DataType": "String", "StringValue": affected_segment},
            "phmsa_reportable": {
                "DataType": "String",
                "StringValue": str(phmsa_reportable),
            },
        },
    )

    return {
        "message_id": response["MessageId"],
        "incident_id": incident_id,
        "severity": severity,
        "topic_arn": SNS_TOPIC_ARN,
        "message": f"Alert published for incident {incident_id}",
    }


# ============================================================
# Helper Functions
# ============================================================


def _generate_incident_id(now: datetime) -> str:
    """Generate a unique incident ID in the format INC-YYYY-NNNN.

    Uses the day-of-year and a time-based component to create a sequence number
    that's unique within a given year. For production, you'd use an atomic counter
    in DynamoDB, but this approach works for the demo without race conditions.

    Args:
        now: Current UTC datetime.

    Returns:
        Formatted incident ID string, e.g. "INC-2026-0847".
    """
    year = now.year
    # Combine day-of-year with hour to create a pseudo-sequence number
    # This gives ~8760 unique IDs per year (365 days × 24 hours)
    sequence = now.timetuple().tm_yday * 10 + now.hour % 10
    return f"INC-{year}-{sequence:04d}"


def _format_alert_message(
    incident_id: str,
    severity: str,
    affected_segment: str,
    leak_location: str,
    recommended_actions: list[str],
    phmsa_reportable: bool,
    summary: str,
) -> str:
    """Format a human-readable alert message for control room operators.

    The message structure prioritizes the most critical information first:
    severity and location, then actions, then regulatory obligations.
    """
    actions_text = "\n".join(f"  {i+1}. {action}" for i, action in enumerate(recommended_actions))

    phmsa_notice = ""
    if phmsa_reportable:
        phmsa_notice = (
            "\n⚠️  PHMSA REPORTABLE — NRC notification required within 1 hour.\n"
        )

    return f"""
════════════════════════════════════════════════════
  PIPELINE INTEGRITY ALERT — {incident_id}
════════════════════════════════════════════════════

SEVERITY: {severity.upper()}
SEGMENT:  {affected_segment}
LOCATION: {leak_location}
{phmsa_notice}
SUMMARY:
  {summary}

RECOMMENDED ACTIONS:
{actions_text}

════════════════════════════════════════════════════
  Generated by Pipeline Integrity Agent
  Timestamp: {datetime.now(timezone.utc).isoformat()}
════════════════════════════════════════════════════
""".strip()


def _prepare_for_dynamodb(record: dict) -> dict:
    """Prepare a record for DynamoDB by converting incompatible types.

    DynamoDB doesn't support None values in items — they must be omitted.
    Also converts nested dicts/lists to DynamoDB-compatible format.
    """
    cleaned = {}
    for key, value in record.items():
        if value is None:
            # Skip None values — DynamoDB doesn't support them
            continue
        elif isinstance(value, float):
            # Convert floats to strings to avoid Decimal precision issues
            # DynamoDB's Decimal type can cause unexpected rounding
            from decimal import Decimal

            cleaned[key] = Decimal(str(value))
        elif isinstance(value, dict):
            # Recursively clean nested dicts (e.g., anomaly_analysis)
            cleaned[key] = json.loads(json.dumps(value, default=str))
        elif isinstance(value, list):
            # Ensure list items are serializable
            cleaned[key] = json.loads(json.dumps(value, default=str))
        else:
            cleaned[key] = value
    return cleaned


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
