# Project Conventions — Pipeline Leak Detection & Integrity Agent

## Overview

This project implements an autonomous Pipeline Integrity Agent using Amazon Bedrock AgentCore and the Strands Agents SDK. The agent monitors SCADA telemetry from 8 stations across a 200-mile natural gas transmission pipeline, detects leaks through contextual AI reasoning, and orchestrates incident response workflows.

## Technology Stack

- **Agent Framework:** Strands Agents SDK with `@tool` decorator pattern
- **Deployment:** Amazon Bedrock AgentCore (Runtime, Memory, Code Interpreter, Gateway, Browser)
- **Infrastructure CLI:** AgentCore CLI
- **Language:** Python 3.11+
- **AWS Region:** us-west-2 (all operations)

## Coding Standards

### Python

- All functions and methods MUST include type hints for parameters and return values
- All code MUST include educational inline comments explaining the reasoning behind key decisions
- Keep implementations minimal and focused on demonstrating core concepts
- Follow PEP 8 style guidelines
- Use `dataclasses` or `pydantic` for data models

### Agent Tools

- All agent tools MUST use the Strands `@tool` decorator pattern
- Tool docstrings serve as the tool description for the agent — make them clear and specific
- Tools should be single-purpose and composable

### AWS CLI

- ALWAYS include `--no-cli-pager` option when executing AWS CLI commands from a terminal
- ALWAYS target `us-west-2` region explicitly (via `--region us-west-2` or environment config)

## Research Requirements

- ALWAYS look up the most up-to-date AWS and Strands documentation using MCP tools before writing implementation code
- Do NOT rely on prior knowledge for AgentCore or Strands Agents APIs — search documentation first
- Reference official AWS documentation: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/
- Reference Strands starter toolkit: https://github.com/aws/bedrock-agentcore-starter-toolkit

## AWS Best Practices

- Follow official AWS documentation patterns and examples
- Use IAM least-privilege principles for all roles and policies
- Use environment variables or AWS Secrets Manager for sensitive configuration
- Implement proper error handling and retries for AWS service calls
- Use structured logging for observability

## Project Structure Guidance

- Keep the codebase flat and navigable — avoid deep nesting
- Separate agent definition, tools, data models, and infrastructure code
- Configuration should be externalized (environment variables or config files)
- Data files (CSVs, reference docs) live in a `data/` directory
