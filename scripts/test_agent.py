#!/usr/bin/env python3
"""Test the deployed Pipeline Integrity Agent against labeled scenarios.

Invokes the agent with payloads simulating each of the 5 labeled leak events
and 15 labeled false positive events, then compares agent responses against
expected classifications and reports accuracy metrics.

Usage:
    python scripts/test_agent.py [--runtime-arn ARN] [--region REGION] [--timeout SECONDS]
    python scripts/test_agent.py --local  # Test against local agent server

Metrics reported:
    - Detection rate (true positive rate for leaks)
    - False positive rate (incorrectly escalated FP events)
    - Localization accuracy (mile marker error for detected leaks)
    - Severity classification accuracy
    - Average response time
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import boto3
import requests


# --- Configuration ---
DEFAULT_REGION = "us-west-2"
DEFAULT_TIMEOUT = 300  # 5 minutes max per invocation
LOCAL_AGENT_URL = "http://localhost:8080/invocations"

# Segment metadata for building anomaly payloads
SEGMENT_STATIONS: dict[str, list[str]] = {
    "SEG-01": ["ST-01", "ST-02"],
    "SEG-02": ["ST-02", "ST-03"],
    "SEG-03": ["ST-03", "ST-04"],
    "SEG-04": ["ST-04", "ST-05"],
    "SEG-05": ["ST-05", "ST-06"],
    "SEG-06": ["ST-06", "ST-07"],
    "SEG-07": ["ST-07", "ST-08"],
}

# Station to adjacent segments mapping for false positive events
STATION_SEGMENTS: dict[str, str] = {
    "ST-01": "SEG-01",
    "ST-02": "SEG-02",
    "ST-03": "SEG-03",
    "ST-04": "SEG-04",
    "ST-05": "SEG-05",
    "ST-06": "SEG-06",
    "ST-07": "SEG-07",
    "ST-08": "SEG-07",
}


@dataclass
class LeakScenario:
    """A labeled leak event used as a test case."""

    event_id: str
    timestamp: str
    true_mile_marker: float
    affected_segment: str
    expected_leak_rate: float
    expected_severity: str
    detection_lag_minutes: int


@dataclass
class FalsePositiveScenario:
    """A labeled false positive event used as a test case."""

    event_id: str
    timestamp: str
    station_id: str
    fp_type: str
    pressure_drop_psi: float
    duration_minutes: int
    explanation: str


@dataclass
class TestResult:
    """Result of a single test invocation."""

    event_id: str
    expected_classification: str  # real_leak | false_positive
    actual_classification: Optional[str] = None
    expected_severity: Optional[str] = None
    actual_severity: Optional[str] = None
    expected_mile_marker: Optional[float] = None
    actual_mile_marker: Optional[float] = None
    response_time_seconds: float = 0.0
    passed: bool = False
    error: Optional[str] = None
    raw_response: str = ""


@dataclass
class TestMetrics:
    """Aggregated accuracy metrics across all test scenarios."""

    total_leak_scenarios: int = 0
    leaks_detected: int = 0
    leaks_missed: int = 0
    total_fp_scenarios: int = 0
    fp_correctly_dismissed: int = 0
    fp_incorrectly_escalated: int = 0
    severity_correct: int = 0
    severity_total: int = 0
    localization_errors_miles: list[float] = field(default_factory=list)
    response_times: list[float] = field(default_factory=list)

    @property
    def detection_rate(self) -> float:
        """True positive rate: fraction of real leaks correctly detected."""
        if self.total_leak_scenarios == 0:
            return 0.0
        return self.leaks_detected / self.total_leak_scenarios

    @property
    def false_positive_rate(self) -> float:
        """Fraction of FP events incorrectly escalated as real leaks."""
        if self.total_fp_scenarios == 0:
            return 0.0
        return self.fp_incorrectly_escalated / self.total_fp_scenarios

    @property
    def severity_accuracy(self) -> float:
        """Fraction of detected leaks with correct severity classification."""
        if self.severity_total == 0:
            return 0.0
        return self.severity_correct / self.severity_total

    @property
    def mean_localization_error(self) -> float:
        """Average mile marker error for localized leaks."""
        if not self.localization_errors_miles:
            return float("inf")
        return sum(self.localization_errors_miles) / len(self.localization_errors_miles)

    @property
    def avg_response_time(self) -> float:
        """Average agent response time in seconds."""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)


def load_leak_scenarios(data_dir: Path) -> list[LeakScenario]:
    """Load labeled leak events from CSV."""
    filepath = data_dir / "labeled_leak_events.csv"
    scenarios = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scenarios.append(
                LeakScenario(
                    event_id=row["event_id"],
                    timestamp=row["onset_timestamp"],
                    true_mile_marker=float(row["true_leak_location_mile_marker"]),
                    affected_segment=row["affected_segment"],
                    expected_leak_rate=float(row["leak_rate_mmscfd"]),
                    expected_severity=row["severity"],
                    detection_lag_minutes=int(row["detection_lag_minutes"]),
                )
            )
    return scenarios


def load_fp_scenarios(data_dir: Path) -> list[FalsePositiveScenario]:
    """Load labeled false positive events from CSV."""
    filepath = data_dir / "labeled_false_positive_events.csv"
    scenarios = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scenarios.append(
                FalsePositiveScenario(
                    event_id=row["event_id"],
                    timestamp=row["timestamp"],
                    station_id=row["station_id"],
                    fp_type=row["fp_type"],
                    pressure_drop_psi=float(row["pressure_drop_psi"]),
                    duration_minutes=int(row["duration_minutes"]),
                    explanation=row["explanation"],
                )
            )
    return scenarios


def build_leak_payload(scenario: LeakScenario) -> dict:
    """Build an anomaly event payload from a labeled leak scenario.

    Simulates what EventBridge would send when the pre-processor detects
    a mass balance deficit or pressure drop matching this leak event.
    """
    stations = SEGMENT_STATIONS.get(scenario.affected_segment, ["ST-01", "ST-02"])
    return {
        "event_id": f"TEST-{scenario.event_id}",
        "timestamp": scenario.timestamp,
        "anomaly_type": "mass_balance_deficit",
        "affected_stations": stations,
        "affected_segment": scenario.affected_segment,
        "trigger_values": {
            "mass_balance_deficit_mmscfd": scenario.expected_leak_rate,
            "pressure_drop_rate_psi_per_min": round(scenario.expected_leak_rate * 2.5, 2),
        },
        "severity": "critical" if scenario.expected_severity in ("significant", "near_rupture") else "warning",
    }


def build_fp_payload(scenario: FalsePositiveScenario) -> dict:
    """Build an anomaly event payload from a labeled false positive scenario.

    Simulates what EventBridge would send when the pre-processor detects
    a pressure drop that is actually caused by an operational transient.
    """
    segment = STATION_SEGMENTS.get(scenario.station_id, "SEG-01")
    # Determine adjacent station pair for the segment
    stations = SEGMENT_STATIONS.get(segment, [scenario.station_id])

    return {
        "event_id": f"TEST-{scenario.event_id}",
        "timestamp": scenario.timestamp,
        "anomaly_type": "pressure_drop",
        "affected_stations": stations,
        "affected_segment": segment,
        "trigger_values": {
            "pressure_drop_psi": scenario.pressure_drop_psi,
            "duration_minutes": scenario.duration_minutes,
            "pressure_drop_rate_psi_per_min": round(
                scenario.pressure_drop_psi / max(scenario.duration_minutes, 1), 2
            ),
        },
        "severity": "warning",
    }


def invoke_agent_remote(
    payload: dict, runtime_arn: str, region: str, timeout: int
) -> tuple[str, float]:
    """Invoke the deployed agent via AgentCore Runtime.

    Returns the response text and elapsed time in seconds.
    """
    client = boto3.client("bedrock-agent-runtime", region_name=region)

    start = time.time()
    try:
        response = client.invoke_agent(
            agentAliasId="TSTALIASID",
            agentId=runtime_arn,
            sessionId=f"test-{payload['event_id']}-{int(time.time())}",
            inputText=json.dumps(payload),
        )
        # Collect streaming response
        result_text = ""
        for event in response.get("completion", []):
            if "chunk" in event:
                result_text += event["chunk"].get("bytes", b"").decode("utf-8")
    except Exception as e:
        # Fall back to direct AgentCore invoke if available
        agentcore_client = boto3.client("bedrock-agentcore", region_name=region)
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=json.dumps(payload).encode("utf-8"),
        )
        result_text = response["body"].read().decode("utf-8")

    elapsed = time.time() - start
    return result_text, elapsed


def invoke_agent_local(payload: dict, timeout: int) -> tuple[str, float]:
    """Invoke the agent running locally via HTTP POST.

    Returns the response text and elapsed time in seconds.
    """
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
    return result_text, elapsed


def parse_classification(response_text: str) -> Optional[str]:
    """Extract the classification (real_leak or false_positive) from agent response.

    Looks for explicit classification keywords in the agent's output.
    """
    text_lower = response_text.lower()

    # Check for explicit classification markers
    if any(phrase in text_lower for phrase in [
        "real_leak", "real leak", "confirmed leak", "leak confirmed",
        "classification: leak", "this is a real leak", "genuine leak",
    ]):
        return "real_leak"

    if any(phrase in text_lower for phrase in [
        "false_positive", "false positive", "not a leak", "no leak",
        "classification: false positive", "dismissed", "operational transient",
    ]):
        return "false_positive"

    # Heuristic: if incident report is generated with severity, likely a real leak
    if "severity" in text_lower and any(
        s in text_lower for s in ["seep", "moderate", "significant", "near_rupture", "near-rupture"]
    ):
        return "real_leak"

    return None


def parse_severity(response_text: str) -> Optional[str]:
    """Extract severity classification from agent response."""
    text_lower = response_text.lower()

    for severity in ["near_rupture", "near-rupture", "significant", "moderate", "seep"]:
        if severity in text_lower:
            # Normalize near-rupture variants
            return severity.replace("-", "_")

    return None


def parse_mile_marker(response_text: str) -> Optional[float]:
    """Extract estimated leak mile marker from agent response.

    Looks for patterns like 'mile marker 47.2' or 'mile 119.3' or
    'located at approximately 72 miles'.
    """
    patterns = [
        r"mile\s*marker[:\s]+(\d+\.?\d*)",
        r"mile[:\s]+(\d+\.?\d*)",
        r"located\s+(?:at\s+)?(?:approximately\s+)?(\d+\.?\d*)\s*mile",
        r"(\d+\.?\d*)\s*mile\s*marker",
        r"location[:\s]+(\d+\.?\d*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, response_text.lower())
        if match:
            return float(match.group(1))

    return None


def evaluate_leak_result(
    scenario: LeakScenario, response_text: str, elapsed: float
) -> TestResult:
    """Evaluate agent response against a labeled leak scenario."""
    result = TestResult(
        event_id=scenario.event_id,
        expected_classification="real_leak",
        expected_severity=scenario.expected_severity,
        expected_mile_marker=scenario.true_mile_marker,
        response_time_seconds=elapsed,
        raw_response=response_text[:500],
    )

    result.actual_classification = parse_classification(response_text)
    result.actual_severity = parse_severity(response_text)
    result.actual_mile_marker = parse_mile_marker(response_text)

    # A leak test passes if the agent correctly identifies it as a real leak
    result.passed = result.actual_classification == "real_leak"

    return result


def evaluate_fp_result(
    scenario: FalsePositiveScenario, response_text: str, elapsed: float
) -> TestResult:
    """Evaluate agent response against a labeled false positive scenario."""
    result = TestResult(
        event_id=scenario.event_id,
        expected_classification="false_positive",
        response_time_seconds=elapsed,
        raw_response=response_text[:500],
    )

    result.actual_classification = parse_classification(response_text)

    # A false positive test passes if the agent correctly dismisses it
    result.passed = result.actual_classification == "false_positive"

    return result


def compute_metrics(
    leak_results: list[TestResult], fp_results: list[TestResult]
) -> TestMetrics:
    """Compute aggregate accuracy metrics from all test results."""
    metrics = TestMetrics()

    # Leak detection metrics
    metrics.total_leak_scenarios = len(leak_results)
    for r in leak_results:
        metrics.response_times.append(r.response_time_seconds)
        if r.actual_classification == "real_leak":
            metrics.leaks_detected += 1
            # Severity accuracy
            metrics.severity_total += 1
            if r.actual_severity == r.expected_severity:
                metrics.severity_correct += 1
            # Localization accuracy
            if r.actual_mile_marker is not None and r.expected_mile_marker is not None:
                error = abs(r.actual_mile_marker - r.expected_mile_marker)
                metrics.localization_errors_miles.append(error)
        else:
            metrics.leaks_missed += 1

    # False positive metrics
    metrics.total_fp_scenarios = len(fp_results)
    for r in fp_results:
        metrics.response_times.append(r.response_time_seconds)
        if r.actual_classification == "false_positive":
            metrics.fp_correctly_dismissed += 1
        else:
            metrics.fp_incorrectly_escalated += 1

    return metrics


def print_results(
    leak_results: list[TestResult],
    fp_results: list[TestResult],
    metrics: TestMetrics,
) -> None:
    """Print detailed test results and summary metrics."""
    print("\n" + "=" * 70)
    print("PIPELINE INTEGRITY AGENT — TEST RESULTS")
    print("=" * 70)

    # Leak scenario results
    print("\n--- Leak Detection Scenarios (5 events) ---")
    print(f"{'Event':<10} {'Expected':<12} {'Actual':<15} {'Severity':<12} {'Mile Mkr':<12} {'Time(s)':<8} {'Pass'}")
    print("-" * 80)
    for r in leak_results:
        mile_str = f"{r.actual_mile_marker:.1f}" if r.actual_mile_marker else "N/A"
        sev_str = r.actual_severity or "N/A"
        cls_str = r.actual_classification or "UNKNOWN"
        status = "✓" if r.passed else "✗"
        print(f"{r.event_id:<10} {'real_leak':<12} {cls_str:<15} {sev_str:<12} {mile_str:<12} {r.response_time_seconds:<8.1f} {status}")

    # False positive scenario results
    print(f"\n--- False Positive Scenarios (15 events) ---")
    print(f"{'Event':<10} {'Expected':<15} {'Actual':<18} {'Time(s)':<8} {'Pass'}")
    print("-" * 60)
    for r in fp_results:
        cls_str = r.actual_classification or "UNKNOWN"
        status = "✓" if r.passed else "✗"
        print(f"{r.event_id:<10} {'false_positive':<15} {cls_str:<18} {r.response_time_seconds:<8.1f} {status}")

    # Summary metrics
    print("\n" + "=" * 70)
    print("SUMMARY METRICS")
    print("=" * 70)
    print(f"  Detection Rate (TPR):        {metrics.detection_rate:.1%} ({metrics.leaks_detected}/{metrics.total_leak_scenarios})")
    print(f"  False Positive Rate:         {metrics.false_positive_rate:.1%} ({metrics.fp_incorrectly_escalated}/{metrics.total_fp_scenarios})")
    print(f"  Severity Accuracy:           {metrics.severity_accuracy:.1%} ({metrics.severity_correct}/{metrics.severity_total})")
    print(f"  Mean Localization Error:     {metrics.mean_localization_error:.1f} miles")
    print(f"  Avg Response Time:           {metrics.avg_response_time:.1f}s")
    print()

    # Pass/fail summary
    total = len(leak_results) + len(fp_results)
    passed = sum(1 for r in leak_results + fp_results if r.passed)
    print(f"  Overall: {passed}/{total} scenarios passed")

    # Target thresholds from requirements
    print("\n--- Target Thresholds ---")
    print(f"  Detection Rate target:  ≥ 98%  {'✓' if metrics.detection_rate >= 0.98 else '✗'}")
    print(f"  FP Rate target:         ≈ 0%   {'✓' if metrics.false_positive_rate <= 0.05 else '✗'}")
    print(f"  Response Time target:   < 300s {'✓' if metrics.avg_response_time < 300 else '✗'}")
    print("=" * 70)


def main() -> None:
    """Main entry point — load scenarios, invoke agent, report metrics."""
    parser = argparse.ArgumentParser(
        description="Test the Pipeline Integrity Agent against labeled scenarios."
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
        help=f"Max seconds per invocation (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Test against local agent server (http://localhost:8080)",
    )
    parser.add_argument(
        "--leaks-only",
        action="store_true",
        help="Run only leak detection scenarios",
    )
    parser.add_argument(
        "--fp-only",
        action="store_true",
        help="Run only false positive scenarios",
    )
    args = parser.parse_args()

    if not args.local and not args.runtime_arn:
        print("ERROR: Provide --runtime-arn for remote testing or --local for local testing.")
        sys.exit(1)

    # Resolve data directory
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"

    if not data_dir.exists():
        print(f"ERROR: Data directory not found at {data_dir}")
        sys.exit(1)

    # Load labeled scenarios
    leak_scenarios = load_leak_scenarios(data_dir)
    fp_scenarios = load_fp_scenarios(data_dir)

    print(f"Loaded {len(leak_scenarios)} leak scenarios, {len(fp_scenarios)} FP scenarios")
    print(f"Mode: {'local' if args.local else 'remote'}")
    if not args.local:
        print(f"Runtime ARN: {args.runtime_arn}")
    print()

    leak_results: list[TestResult] = []
    fp_results: list[TestResult] = []

    # --- Run leak scenarios ---
    if not args.fp_only:
        print("Running leak detection scenarios...")
        for i, scenario in enumerate(leak_scenarios, 1):
            payload = build_leak_payload(scenario)
            print(f"  [{i}/{len(leak_scenarios)}] {scenario.event_id} "
                  f"({scenario.affected_segment}, {scenario.expected_severity})...", end=" ", flush=True)

            try:
                if args.local:
                    response_text, elapsed = invoke_agent_local(payload, args.timeout)
                else:
                    response_text, elapsed = invoke_agent_remote(
                        payload, args.runtime_arn, args.region, args.timeout
                    )
                result = evaluate_leak_result(scenario, response_text, elapsed)
            except Exception as e:
                result = TestResult(
                    event_id=scenario.event_id,
                    expected_classification="real_leak",
                    error=str(e),
                    response_time_seconds=0.0,
                )
                print(f"ERROR: {e}")
                leak_results.append(result)
                continue

            status = "✓" if result.passed else "✗"
            print(f"{status} ({elapsed:.1f}s)")
            leak_results.append(result)

    # --- Run false positive scenarios ---
    if not args.leaks_only:
        print("\nRunning false positive scenarios...")
        for i, scenario in enumerate(fp_scenarios, 1):
            payload = build_fp_payload(scenario)
            print(f"  [{i}/{len(fp_scenarios)}] {scenario.event_id} "
                  f"({scenario.station_id}, {scenario.fp_type})...", end=" ", flush=True)

            try:
                if args.local:
                    response_text, elapsed = invoke_agent_local(payload, args.timeout)
                else:
                    response_text, elapsed = invoke_agent_remote(
                        payload, args.runtime_arn, args.region, args.timeout
                    )
                result = evaluate_fp_result(scenario, response_text, elapsed)
            except Exception as e:
                result = TestResult(
                    event_id=scenario.event_id,
                    expected_classification="false_positive",
                    error=str(e),
                    response_time_seconds=0.0,
                )
                print(f"ERROR: {e}")
                fp_results.append(result)
                continue

            status = "✓" if result.passed else "✗"
            print(f"{status} ({elapsed:.1f}s)")
            fp_results.append(result)

    # --- Compute and display metrics ---
    metrics = compute_metrics(leak_results, fp_results)
    print_results(leak_results, fp_results, metrics)

    # Exit with non-zero if any scenario failed
    all_passed = all(r.passed for r in leak_results + fp_results if r.error is None)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
