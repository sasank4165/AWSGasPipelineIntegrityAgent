#!/bin/bash
# Run this script inside a SageMaker Studio JupyterLab terminal
# to set up and launch the Pipeline Integrity Dashboard.
#
# Usage:
#   1. Open Studio: https://rkwcalzou9nfpie.studio.us-west-2.sagemaker.aws
#   2. Open a terminal and run: bash setup_studio.sh
#
# The dashboard will be accessible at:
#   https://rkwcalzou9nfpie.studio.us-west-2.sagemaker.aws/jupyterlab/default/proxy/8501/

set -e

echo "=== Pipeline Integrity Dashboard Setup ==="

# Install dependencies
pip install -q streamlit plotly pandas boto3

# Set environment variables for AWS data access
export AWS_DEFAULT_REGION=us-west-2
export SCADA_BUCKET=pipeline-integrity-agent-data-211125430374-dev
export SEGMENTS_TABLE=pipeline-integrity-agent-PipelineSegments-dev
export VALVE_TABLE=pipeline-integrity-agent-ValveStatus-dev
export INCIDENTS_TABLE=pipeline-integrity-agent-Incidents-dev
export SCADA_S3_KEY=scada/scada_timeseries.csv

echo "Starting Streamlit dashboard on port 8501..."
echo ""
echo "Access URL: https://rkwcalzou9nfpie.studio.us-west-2.sagemaker.aws/jupyterlab/default/proxy/8501/"
echo ""

streamlit run app.py --server.port 8501 --server.headless true --server.enableCORS false --server.enableXsrfProtection false
