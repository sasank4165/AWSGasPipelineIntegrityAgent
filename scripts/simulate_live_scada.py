#!/usr/bin/env python3
"""Simulate live SCADA data by replaying the CSV in accelerated time.

Reads the SCADA timeseries CSV and writes a rolling window of "current"
readings to a live S3 key every N seconds. The dashboard reads from this
live key to show real-time-like data.

Usage:
    python3 scripts/simulate_live_scada.py [--speed 10] [--interval 5]

    --speed: How many data intervals to advance per real second (default 10)
    --interval: Seconds between S3 writes (default 5)

The script writes to: s3://<bucket>/scada/live_readings.csv
The dashboard should read from this key for the overview page.
"""

import argparse
import os
import sys
import time
from io import StringIO
from pathlib import Path

import boto3
import pandas as pd

DEFAULT_REGION = "us-west-2"
DEFAULT_BUCKET = "pipeline-integrity-agent-data-211125430374-dev"
LIVE_KEY = "scada/live_readings.csv"
WINDOW_SIZE = 80  # Keep last 80 rows (10 per station × 8 stations = ~10 time steps)


def main():
    parser = argparse.ArgumentParser(description="Simulate live SCADA data replay")
    parser.add_argument("--speed", type=int, default=10, help="Data intervals per real second")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between S3 writes")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--region", default=DEFAULT_REGION)
    args = parser.parse_args()

    # Load full SCADA CSV — try S3 first, then local file
    project_root = Path(__file__).resolve().parent.parent
    csv_path = project_root / "data" / "scada_timeseries.csv"

    try:
        print("Loading SCADA data from S3...")
        s3 = boto3.client("s3", region_name=args.region)
        response = s3.get_object(Bucket=args.bucket, Key="scada/scada_timeseries.csv")
        csv_content = response["Body"].read().decode("utf-8")
        from io import StringIO
        df = pd.read_csv(StringIO(csv_content))
        print(f"  Loaded {len(df)} rows from S3")
    except Exception:
        if not csv_path.exists():
            print(f"ERROR: Cannot load SCADA data from S3 or {csv_path}")
            sys.exit(1)
        print(f"Loading SCADA data from local file: {csv_path}")
        df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    total_rows = len(df)
    rows_per_step = 8  # 8 stations per time step
    steps_per_write = args.speed * args.interval  # How many time steps to advance per write

    s3 = boto3.client("s3", region_name=args.region)

    print(f"Simulating live SCADA data")
    print(f"  Bucket: {args.bucket}")
    print(f"  Key: {LIVE_KEY}")
    print(f"  Speed: {args.speed}x | Write interval: {args.interval}s")
    print(f"  Total rows: {total_rows} | Window: {WINDOW_SIZE} rows")
    print(f"  Press Ctrl+C to stop")
    print()

    cursor = 0
    while True:
        # Get the current window of data
        end_idx = min(cursor + WINDOW_SIZE, total_rows)
        window = df.iloc[cursor:end_idx]

        # Write to S3
        csv_buffer = StringIO()
        window.to_csv(csv_buffer, index=False)
        s3.put_object(
            Bucket=args.bucket,
            Key=LIVE_KEY,
            Body=csv_buffer.getvalue().encode("utf-8"),
            ContentType="text/csv",
        )

        latest_time = window["timestamp"].max()
        print(f"  [{latest_time}] Wrote {len(window)} rows (cursor: {cursor}/{total_rows})")

        # Advance cursor
        cursor += rows_per_step * steps_per_write
        if cursor >= total_rows:
            cursor = 0  # Loop back to start
            print("  --- Looping back to start ---")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
