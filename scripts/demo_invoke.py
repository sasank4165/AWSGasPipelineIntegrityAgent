#!/usr/bin/env python3
"""Demo invocation of the Pipeline Integrity Agent with a single scenario.

Invokes the agent with the example scenario from the use case: Station 5
experiences a pressure drop of 12 PSI in 8 minutes, triggering a leak
investigation. Prints the full incident report output for demo purposes.

Usage:
    python scripts/demo_invoke.py --runtime-arn ARN [--region REGION]
    python scripts/demo_invoke.py --local  # Against local agent server

The scenario simulates a moderate leak on SEG-05 between ST-05 and ST-06,
which the agent should detect, localize, assess severity, and produce
a complete incident response package.
"""

import argparse
import json
import sys
import time

import boto3
import requests


# --- Configuration ---
DEFAULT_REGION = "us-west-2"
DEFAULT_TIMEOUT = 300  # 5 minutes max
LOCAL_AGENT_URL = "http://localhost:8080/invocations"

# Demo scenario: Station 5 pressure drops 12 PSI in 8 minutes
# This matches labeled event LK-002 characteristics (SEG-05, moderate severity)
DEMO_PAYLOAD = {
    "event_id": "DEMO-2026-001",
    "timestamp": "2026-01-04T23:55:00Z",
    "anomaly_type": "pressure_drop",
    "affected_stations": ["ST-05", "ST-06"],
    "affected_segment": "SEG-05",
    "trigger_values": {
        "pressure_drop_psi": 12.0,
        "duration_minutes": 8,
        "pressure_drop_rate_psi_per_min": 1.5,
        "mass_balance_deficit_mmscfd": 0.52,
        "station_id": "ST-05",
    },
    "severity": "warning",
}


def invoke_agent_remote(payload: dict, runtime_arn: str, region: str, timeout: int) -> str:
    """Invoke the deployed agent via AgentCore Runtime and return the response."""
    client = boto3.client("bedrock-agentcore", region_name=region)

    print(f"Invoking agent at: {runtime_arn}")
    print(f"Region: {region}")
    print(f"Timeout: {timeout}s")
    print()

    start = time.time()
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=json.dumps(payload).encode("utf-8"),
        )
        result_text = response["body"].read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Agent invocation failed: {e}") from e

    elapsed = time.time() - start
    print(f"Agent responded in {elapsed:.1f} seconds")
    return result_text


def invoke_agent_local(payload: dict, timeout: int) -> str:
    """Invoke the agent running locally via HTTP POST."""
    print(f"Invoking local agent at: {LOCAL_AGENT_URL}")
    print(f"Timeout: {timeout}s")
    print()

    start = time.time()
    try:
        resp = requests.post(
            LOCAL_AGENT_URL,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        result_text = resp.text
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Local agent invocation failed: {e}") from e

    elapsed = time.time() - start
    print(f"Agent responded in {elapsed:.1f} seconds")
    return result_text


def print_demo_output(payload: dict, response_text: str) -> None:
    """Print the full demo scenario and agent response in a readable format."""
    print("\n" + "=" * 70)
    print("PIPELINE INTEGRITY AGENT — DEMO INVOCATION")
    print("=" * 70)

    print("\n--- Scenario ---")
    print(f"  Event ID:          {payload['event_id']}")
    print(f"  Timestamp:         {payload['timestamp']}")
    print(f"  Anomaly Type:      {payload['anomaly_type']}")
    print(f"  Affected Stations: {', '.join(payload['affected_stations'])}")
    print(f"  Affected Segment:  {payload['affected_segment']}")
    print(f"  Severity:          {payload['severity']}")
    print(f"  Trigger Values:")
    for key, value in payload["trigger_values"].items():
        print(f"    {key}: {value}")

    print("\n--- Agent Response (Full Incident Report) ---")
    print()
    print(response_text)
    print()
    print("=" * 70)
    print("END OF DEMO")
    print("=" * 70)


def main() -> None:
    """Main entry point — invoke agent with demo scenario and display results."""
    parser = argparse.ArgumentParser(
        description="Demo invocation of the Pipeline Integrity Agent."
    )
    parser.add_argument(
        "--runtime-arn",
        help="AgentCore Runtime ARN for the deployed agent",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Max seconds to wait for response (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Invoke against local agent server (http://localhost:8080)",
    )
    parser.add_argument(
        "--payload-file",
        help="Path to a custom JSON payload file (overrides default demo scenario)",
    )
    args = parser.parse_args()

    if not args.local and not args.runtime_arn:
        print("ERROR: Provide --runtime-arn for remote invocation or --local for local testing.")
        sys.exit(1)

    # Use custom payload if provided, otherwise use the default demo scenario
    if args.payload_file:
        try:
            with open(args.payload_file) as f:
                payload = json.load(f)
            print(f"Using custom payload from: {args.payload_file}")
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"ERROR: Could not load payload file: {e}")
            sys.exit(1)
    else:
        payload = DEMO_PAYLOAD
        print("Using default demo scenario: Station 5 pressure drops 12 PSI in 8 minutes")

    print()

    # Invoke the agent
    try:
        if args.local:
            response_text = invoke_agent_local(payload, args.timeout)
        else:
            response_text = invoke_agent_remote(payload, args.runtime_arn, args.region, args.timeout)
    except RuntimeError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    # Display the full output
    print_demo_output(payload, response_text)


if __name__ == "__main__":
    main()
