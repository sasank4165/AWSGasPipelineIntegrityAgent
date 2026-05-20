"""Shared test configuration — sets AWS environment variables before handler imports.

The Lambda handlers initialize boto3 clients at module level, so we must set
the AWS_DEFAULT_REGION before any handler module is imported. This conftest
runs before test collection and ensures the environment is ready.
"""

import os

# Set AWS region before any boto3 client initialization occurs at import time
os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"

# Lambda-specific environment variables
os.environ["SCADA_BUCKET"] = "test-bucket"
os.environ["SEGMENTS_TABLE"] = "test-segments-table"
os.environ["VALVE_TABLE"] = "test-valve-table"
os.environ["INCIDENTS_TABLE"] = "test-incidents-table"
os.environ["SNS_TOPIC_ARN"] = "arn:aws:sns:us-west-2:123456789012:test-topic"
