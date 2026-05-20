#!/usr/bin/env python3
"""Create Bedrock Knowledge Base with OpenSearch Serverless vector store.

Creates:
1. OpenSearch Serverless encryption/network/access policies
2. OpenSearch Serverless collection (VECTORSEARCH)
3. Vector index (pipeline-kb-index) with Titan Embed v2 dimensions
4. Bedrock Knowledge Base with S3 data source
5. Triggers ingestion job to index PDFs

Usage:
    python3 scripts/create_knowledge_base.py --region us-west-2 --account-id 123456789012
"""

import argparse
import json
import time

import boto3


def main():
    parser = argparse.ArgumentParser(description="Create Bedrock Knowledge Base")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--account-id", required=True)
    args = parser.parse_args()

    region = args.region
    account_id = args.account_id
    bucket_name = f"pipeline-integrity-agent-data-{account_id}-dev"
    kb_role_name = "pipeline-integrity-agent-kb-role"

    aoss = boto3.client("opensearchserverless", region_name=region)
    iam = boto3.client("iam", region_name=region)
    sts = boto3.client("sts", region_name=region)
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    caller_arn = sts.get_caller_identity()["Arn"]

    # --- Step 1: Create KB IAM role ---
    print("Creating KB IAM role...")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": account_id}}
        }]
    }
    try:
        iam.create_role(RoleName=kb_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
    except iam.exceptions.EntityAlreadyExistsException:
        pass

    kb_role_arn = f"arn:aws:iam::{account_id}:role/{kb_role_name}"

    iam.put_role_policy(RoleName=kb_role_name, PolicyName="S3Access", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": [f"arn:aws:s3:::{bucket_name}", f"arn:aws:s3:::{bucket_name}/knowledge-base/*"]}]
    }))
    iam.put_role_policy(RoleName=kb_role_name, PolicyName="BedrockEmbedding", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"}]
    }))
    iam.put_role_policy(RoleName=kb_role_name, PolicyName="AOSSAccess", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "aoss:APIAccessAll", "Resource": f"arn:aws:aoss:{region}:{account_id}:collection/*"}]
    }))
    print(f"  KB role: {kb_role_arn}")

    # --- Step 2: Create OpenSearch Serverless policies ---
    print("Creating AOSS policies...")
    try:
        aoss.create_security_policy(name="pia-kb-enc", type="encryption", policy=json.dumps({
            "Rules": [{"ResourceType": "collection", "Resource": ["collection/pia-kb-collection"]}], "AWSOwnedKey": True
        }))
    except aoss.exceptions.ConflictException:
        pass

    try:
        aoss.create_security_policy(name="pia-kb-net", type="network", policy=json.dumps([{
            "Rules": [{"ResourceType": "collection", "Resource": ["collection/pia-kb-collection"]}, {"ResourceType": "dashboard", "Resource": ["collection/pia-kb-collection"]}],
            "AllowFromPublic": True
        }]))
    except aoss.exceptions.ConflictException:
        pass

    try:
        aoss.create_access_policy(name="pia-kb-access", type="data", policy=json.dumps([{
            "Rules": [
                {"ResourceType": "index", "Resource": ["index/pia-kb-collection/*"], "Permission": ["aoss:CreateIndex", "aoss:UpdateIndex", "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument"]},
                {"ResourceType": "collection", "Resource": ["collection/pia-kb-collection"], "Permission": ["aoss:CreateCollectionItems", "aoss:DescribeCollectionItems", "aoss:UpdateCollectionItems"]}
            ],
            "Principal": [kb_role_arn, caller_arn, f"arn:aws:iam::{account_id}:root"]
        }]))
    except aoss.exceptions.ConflictException:
        pass

    # --- Step 3: Create collection ---
    print("Creating AOSS collection...")
    try:
        coll_resp = aoss.create_collection(name="pia-kb-collection", type="VECTORSEARCH")
        collection_id = coll_resp["createCollectionDetail"]["id"]
    except aoss.exceptions.ConflictException:
        colls = aoss.list_collections(collectionFilters={"name": "pia-kb-collection"})
        collection_id = colls["collectionSummaries"][0]["id"]

    # Wait for ACTIVE
    print(f"  Collection ID: {collection_id}. Waiting for ACTIVE...")
    endpoint = ""
    for i in range(60):
        time.sleep(10)
        detail = aoss.batch_get_collection(ids=[collection_id])
        status = detail["collectionDetails"][0]["status"]
        if status == "ACTIVE":
            endpoint = detail["collectionDetails"][0]["collectionEndpoint"]
            print(f"  Collection ACTIVE: {endpoint}")
            break
        if i % 6 == 0:
            print(f"    Status: {status} ({(i+1)*10}s)")

    if not endpoint:
        print("ERROR: Collection not active after 10 min")
        return

    # --- Step 4: Create vector index ---
    print("Creating vector index...")
    try:
        from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

        host = endpoint.replace("https://", "")
        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, region, "aoss")

        os_client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth, use_ssl=True, verify_certs=True,
            connection_class=RequestsHttpConnection, timeout=30
        )

        index_body = {
            "settings": {"index": {"knn": True, "number_of_shards": 2, "number_of_replicas": 0}},
            "mappings": {"properties": {
                "embedding": {"type": "knn_vector", "dimension": 1024, "method": {"engine": "faiss", "name": "hnsw", "parameters": {"m": 16, "ef_construction": 512}}},
                "text": {"type": "text"},
                "metadata": {"type": "text"}
            }}
        }
        os_client.indices.create(index="pipeline-kb-index", body=index_body)
        print("  Index created: pipeline-kb-index")
    except Exception as e:
        if "already exists" in str(e).lower() or "resource_already_exists" in str(e).lower():
            print("  Index already exists")
        else:
            print(f"  Index creation error: {e}")

    # --- Step 5: Create Bedrock Knowledge Base ---
    print("Creating Bedrock Knowledge Base...")
    collection_arn = f"arn:aws:aoss:{region}:{account_id}:collection/{collection_id}"

    try:
        kb_response = bedrock_agent.create_knowledge_base(
            name="pipeline-integrity-kb",
            description="Pipeline operating procedures and DOT PHMSA regulatory references",
            roleArn=kb_role_arn,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
                }
            },
            storageConfiguration={
                "type": "OPENSEARCH_SERVERLESS",
                "opensearchServerlessConfiguration": {
                    "collectionArn": collection_arn,
                    "vectorIndexName": "pipeline-kb-index",
                    "fieldMapping": {"vectorField": "embedding", "textField": "text", "metadataField": "metadata"}
                }
            }
        )
        kb_id = kb_response["knowledgeBase"]["knowledgeBaseId"]
        print(f"  KB created: {kb_id}")
    except Exception as e:
        if "already exists" in str(e).lower() or "ConflictException" in str(type(e).__name__):
            # Find existing KB
            kbs = bedrock_agent.list_knowledge_bases()
            kb_id = next(kb["knowledgeBaseId"] for kb in kbs["knowledgeBaseSummaries"] if "pipeline" in kb["name"])
            print(f"  KB exists: {kb_id}")
        else:
            raise

    # Wait for ACTIVE
    for i in range(12):
        time.sleep(5)
        kb = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        if kb["knowledgeBase"]["status"] == "ACTIVE":
            break

    # --- Step 6: Create S3 data source and sync ---
    print("Creating data source and syncing...")
    try:
        ds_response = bedrock_agent.create_data_source(
            knowledgeBaseId=kb_id,
            name="pipeline-docs-s3",
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{bucket_name}",
                    "inclusionPrefixes": ["knowledge-base/"]
                }
            }
        )
        ds_id = ds_response["dataSource"]["dataSourceId"]
    except Exception as e:
        if "ConflictException" in str(type(e).__name__) or "already exists" in str(e).lower():
            dss = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
            ds_id = dss["dataSourceSummaries"][0]["dataSourceId"]
        else:
            raise

    # Start sync
    sync_response = bedrock_agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    job_id = sync_response["ingestionJob"]["ingestionJobId"]
    print(f"  Ingestion job: {job_id}")

    for i in range(30):
        time.sleep(10)
        job = bedrock_agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job_id)
        status = job["ingestionJob"]["status"]
        if status == "COMPLETE":
            stats = job["ingestionJob"].get("statistics", {})
            print(f"  Sync COMPLETE: {stats.get('numberOfDocumentsScanned', 0)} docs scanned, {stats.get('numberOfNewDocumentsIndexed', 0)} indexed")
            break
        elif status == "FAILED":
            print(f"  Sync FAILED: {job['ingestionJob'].get('failureReasons', 'unknown')}")
            break
        if i % 3 == 0:
            print(f"    Syncing... ({(i+1)*10}s)")

    print(f"\n  Knowledge Base ID: {kb_id}")
    print("  Knowledge Base setup complete!")


if __name__ == "__main__":
    main()
