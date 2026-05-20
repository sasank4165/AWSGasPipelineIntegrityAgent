#!/usr/bin/env python3
"""Trigger a Bedrock Knowledge Base data source sync and wait for completion.

After PDFs are uploaded to the knowledge-base/ prefix in S3, this script
starts an ingestion job on the Bedrock Knowledge Base and polls until
the sync finishes (or fails).

Usage:
    python scripts/sync_knowledge_base.py [--stack-name STACK_NAME] [--region REGION]
"""

import argparse
import sys
import time

import boto3

DEFAULT_STACK_NAME = "pipeline-integrity-agent"
DEFAULT_REGION = "us-west-2"
POLL_INTERVAL_SECONDS = 10
MAX_WAIT_SECONDS = 600  # 10 minutes max wait


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


def get_data_source_id(
    bedrock_agent_client, knowledge_base_id: str
) -> str | None:
    """Find the first data source ID associated with the Knowledge Base."""
    response = bedrock_agent_client.list_data_sources(
        knowledgeBaseId=knowledge_base_id
    )
    sources = response.get("dataSourceSummaries", [])
    if not sources:
        return None
    return sources[0]["dataSourceId"]


def start_ingestion_job(
    bedrock_agent_client, knowledge_base_id: str, data_source_id: str
) -> str:
    """Start a data source ingestion job and return the job ID."""
    response = bedrock_agent_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
    )
    job_id = response["ingestionJob"]["ingestionJobId"]
    return job_id


def wait_for_ingestion(
    bedrock_agent_client,
    knowledge_base_id: str,
    data_source_id: str,
    job_id: str,
) -> str:
    """Poll the ingestion job until it completes or times out. Returns final status."""
    elapsed = 0
    print(f"  Waiting for ingestion job {job_id} to complete...")

    while elapsed < MAX_WAIT_SECONDS:
        response = bedrock_agent_client.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            ingestionJobId=job_id,
        )
        status = response["ingestionJob"]["status"]
        print(f"  [{elapsed}s] Status: {status}")

        if status in ("COMPLETE", "FAILED", "STOPPED"):
            return status

        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    print(f"  TIMEOUT: Ingestion did not complete within {MAX_WAIT_SECONDS}s.")
    return "TIMEOUT"


def main() -> None:
    """Main entry point — sync the Knowledge Base data source."""
    parser = argparse.ArgumentParser(
        description="Trigger Bedrock Knowledge Base sync after PDF upload."
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

    print(f"Stack: {args.stack_name} | Region: {args.region}")

    # Get Knowledge Base ID from stack outputs
    outputs = get_stack_outputs(args.stack_name, args.region)
    kb_id = outputs.get("KnowledgeBaseId")

    if not kb_id:
        print("ERROR: KnowledgeBaseId not found in stack outputs.")
        sys.exit(1)

    print(f"Knowledge Base ID: {kb_id}")

    # Initialize Bedrock Agent client
    bedrock_agent = boto3.client("bedrock-agent", region_name=args.region)

    # Find the data source attached to this KB
    data_source_id = get_data_source_id(bedrock_agent, kb_id)
    if not data_source_id:
        print("ERROR: No data source found for this Knowledge Base.")
        sys.exit(1)

    print(f"Data Source ID: {data_source_id}")

    # Start the ingestion job
    print("\n--- Starting Knowledge Base ingestion job ---")
    job_id = start_ingestion_job(bedrock_agent, kb_id, data_source_id)
    print(f"  Ingestion Job ID: {job_id}")

    # Wait for completion
    final_status = wait_for_ingestion(
        bedrock_agent, kb_id, data_source_id, job_id
    )

    if final_status == "COMPLETE":
        print("\n=== Knowledge Base sync completed successfully ===")
    else:
        print(f"\n=== Knowledge Base sync ended with status: {final_status} ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
