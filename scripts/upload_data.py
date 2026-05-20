#!/usr/bin/env python3
"""Upload pipeline data files to S3 and populate DynamoDB tables.

Uploads CSV files to S3 under appropriate prefixes and PDFs to the
knowledge-base/ prefix. Populates PipelineSegments and ValveStatus
DynamoDB tables from their respective CSV files.

Usage:
    python scripts/upload_data.py [--stack-name STACK_NAME] [--region REGION]
"""

import argparse
import csv
import os
import sys
from decimal import Decimal
from pathlib import Path

import boto3

# Default configuration
DEFAULT_STACK_NAME = "pipeline-integrity-agent"
DEFAULT_REGION = "us-west-2"

# Mapping of CSV files to their S3 prefix destinations
CSV_PREFIX_MAP: dict[str, str] = {
    "scada_timeseries.csv": "scada/",
    "gas_composition.csv": "gas-composition/",
    "weather_conditions.csv": "weather/",
    "cathodic_protection.csv": "integrity/",
    "inspection_history.csv": "integrity/",
    "row_encroachment.csv": "integrity/",
    "labeled_leak_events.csv": "labeled-events/",
    "labeled_false_positive_events.csv": "labeled-events/",
    "pipeline_segment_metadata.csv": "metadata/",
    "valve_status.csv": "metadata/",
}


def get_stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    """Retrieve CloudFormation stack outputs as a key-value dict."""
    cfn = boto3.client("cloudformation", region_name=region)
    try:
        response = cfn.describe_stacks(StackName=stack_name)
    except cfn.exceptions.ClientError as e:
        print(f"ERROR: Could not describe stack '{stack_name}': {e}")
        sys.exit(1)

    outputs = {}
    for output in response["Stacks"][0].get("Outputs", []):
        outputs[output["OutputKey"]] = output["OutputValue"]
    return outputs


def upload_csv_files(s3_client, bucket: str, data_dir: Path) -> None:
    """Upload all CSV files to S3 under their designated prefixes."""
    print("\n--- Uploading CSV files to S3 ---")
    for filename, prefix in CSV_PREFIX_MAP.items():
        filepath = data_dir / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} (not found)")
            continue
        s3_key = f"{prefix}{filename}"
        print(f"  Uploading {filename} -> s3://{bucket}/{s3_key}")
        s3_client.upload_file(str(filepath), bucket, s3_key)
    print("  CSV upload complete.")


def upload_pdf_files(s3_client, bucket: str, data_dir: Path) -> None:
    """Upload PDF reference documents to the knowledge-base/ prefix in S3."""
    print("\n--- Uploading PDFs to knowledge-base/ prefix ---")
    ref_dir = data_dir / "reference_docs"
    if not ref_dir.exists():
        print("  SKIP: reference_docs directory not found")
        return

    for filepath in ref_dir.glob("*.pdf"):
        s3_key = f"knowledge-base/{filepath.name}"
        print(f"  Uploading {filepath.name} -> s3://{bucket}/{s3_key}")
        s3_client.upload_file(str(filepath), bucket, s3_key)
    print("  PDF upload complete.")



def populate_pipeline_segments_table(
    dynamodb_resource, table_name: str, data_dir: Path
) -> None:
    """Load pipeline_segment_metadata.csv into the PipelineSegments DynamoDB table."""
    print(f"\n--- Populating DynamoDB table: {table_name} ---")
    filepath = data_dir / "pipeline_segment_metadata.csv"
    if not filepath.exists():
        print("  SKIP: pipeline_segment_metadata.csv not found")
        return

    table = dynamodb_resource.Table(table_name)
    count = 0

    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields from string to appropriate types
            item = {
                "segment_id": row["segment_id"],
                "from_station": row["from_station"],
                "to_station": row["to_station"],
                "length_miles": Decimal(row["length_miles"]),
                "diameter_in": Decimal(row["diameter_in"]),
                "wall_thickness_in": Decimal(row["wall_thickness_in"]),
                "material_grade": row["material_grade"],
                "max_operating_pressure_psi": Decimal(row["max_operating_pressure_psi"]),
                "elevation_start_ft": Decimal(row["elevation_start_ft"]),
                "elevation_end_ft": Decimal(row["elevation_end_ft"]),
                # Store valve locations as a list of strings (DynamoDB number set alternative)
                "valve_locations_mile_markers": [
                    Decimal(v.strip())
                    for v in row["valve_locations_mile_markers"].split(",")
                    if v.strip()
                ],
                "maop_psi": Decimal(row["maop_psi"]),
            }
            table.put_item(Item=item)
            count += 1

    print(f"  Loaded {count} segments into {table_name}.")


def populate_valve_status_table(
    dynamodb_resource, table_name: str, data_dir: Path
) -> None:
    """Load valve_status.csv into the ValveStatus DynamoDB table."""
    print(f"\n--- Populating DynamoDB table: {table_name} ---")
    filepath = data_dir / "valve_status.csv"
    if not filepath.exists():
        print("  SKIP: valve_status.csv not found")
        return

    table = dynamodb_resource.Table(table_name)
    count = 0

    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = {
                "valve_id": row["valve_id"],
                "segment_id": row["segment_id"],
                "date": row["date"],
                "position_pct": Decimal(row["position_pct"]),
                "state": row["state"],
                "response_time_sec": Decimal(row["response_time_sec"]),
                "leak_test_result": row["leak_test_result"],
            }
            table.put_item(Item=item)
            count += 1

    print(f"  Loaded {count} valve records into {table_name}.")


def main() -> None:
    """Main entry point — parse args, resolve stack outputs, upload data."""
    parser = argparse.ArgumentParser(
        description="Upload pipeline data to S3 and populate DynamoDB tables."
    )
    parser.add_argument(
        "--stack-name",
        default=DEFAULT_STACK_NAME,
        help=f"CloudFormation stack name (default: {DEFAULT_STACK_NAME})",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION})",
    )
    args = parser.parse_args()

    # Resolve project root (one level up from scripts/)
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"

    if not data_dir.exists():
        print(f"ERROR: Data directory not found at {data_dir}")
        sys.exit(1)

    print(f"Stack: {args.stack_name} | Region: {args.region}")
    print(f"Data directory: {data_dir}")

    # Fetch resource names from CloudFormation outputs
    outputs = get_stack_outputs(args.stack_name, args.region)
    bucket_name = outputs.get("DataBucketName")
    segments_table = outputs.get("PipelineSegmentsTableName")
    valve_table = outputs.get("ValveStatusTableName")

    if not bucket_name:
        print("ERROR: DataBucketName not found in stack outputs.")
        sys.exit(1)

    print(f"S3 Bucket: {bucket_name}")
    print(f"Segments Table: {segments_table}")
    print(f"Valve Table: {valve_table}")

    # Initialize AWS clients
    s3_client = boto3.client("s3", region_name=args.region)
    dynamodb = boto3.resource("dynamodb", region_name=args.region)

    # Upload files to S3
    upload_csv_files(s3_client, bucket_name, data_dir)
    upload_pdf_files(s3_client, bucket_name, data_dir)

    # Populate DynamoDB tables
    if segments_table:
        populate_pipeline_segments_table(dynamodb, segments_table, data_dir)
    else:
        print("\n  SKIP: PipelineSegmentsTableName not in stack outputs.")

    if valve_table:
        populate_valve_status_table(dynamodb, valve_table, data_dir)
    else:
        print("\n  SKIP: ValveStatusTableName not in stack outputs.")

    print("\n=== Data upload complete ===")


if __name__ == "__main__":
    main()
