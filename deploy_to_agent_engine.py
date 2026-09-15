import json
import os
import sys
import subprocess
import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from google.api_core import exceptions
from google.cloud import storage, secretmanager

# ── Environment selection ────────────────────────────────────────────────────
# Override by setting DEPLOYMENT_ENVIRONMENT=prod before running
environmentsuffix = os.getenv("DEPLOYMENT_ENVIRONMENT", "dev").lower()
load_dotenv(dotenv_path=f".env.{environmentsuffix}")

# ── Agent and Deployment Configuration ──────────────────────────────────────
PROJECT_ID                  = os.getenv("GCP_CLOUD_PROJECT", "")
GOOGLE_CLOUD_STAGING_BUCKET = os.getenv("GOOGLE_CLOUD_STAGING_BUCKET", "")
GOOGLE_CLOUD_LOCATION       = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_NAME                  = os.getenv("AGENT_NAME", "a2ui-demo-agent")
AGENT_DISPLAY_NAME          = os.getenv("AGENT_DISPLAY_NAME", "A2UI Demo Agent")
AGENT_DESCRIPTION           = os.getenv("AGENT_DESCRIPTION", "ADK agent that emits A2UI follow-up buttons as a DataPart.")
BUCKET_NAME                 = os.getenv("BUCKET_NAME", "")
SECRET_NAME                 = os.getenv("SECRET_NAME", "")

# ── Agent env vars ───────────────────────────────────────────────────────────
# Start with any vars that should always be set on the deployed agent
agent_env_vars: dict = {}

# Inject local env vars that start with AGENT_VAR_ (optional convention)
for key, value in os.environ.items():
    if key.startswith("AGENT_VAR_"):
        agent_env_vars[key.removeprefix("AGENT_VAR_")] = str(value)

print(
    f"Environment variables ({len(agent_env_vars)}) configured for the agent: "
    f"{sorted(agent_env_vars.keys())}"
)

# ── Continue with Agent Deployment ───────────────────────────────────────────
print(f"\nDeploying agent '{AGENT_DISPLAY_NAME}' to project '{PROJECT_ID}'...")

from agent.agent import root_agent  # noqa: E402 — import after env is set up

vertexai.init(project=PROJECT_ID, location=GOOGLE_CLOUD_LOCATION,staging_bucket=GOOGLE_CLOUD_STAGING_BUCKET)

app = AdkApp(
    agent=root_agent,
    enable_tracing=True,
)

# Check whether the agent already exists (match on display name)
agent = next(
    (a for a in agent_engines.list() if a.display_name == AGENT_DISPLAY_NAME),
    None,
)
print(
    f"Found agent! Resource name: {agent.resource_name}, "
    f"display name: {agent.display_name}, name: {agent.name}"
    if agent else "No existing agent found. Creating a new one..."
)

# Pin aiplatform + adk to a known-compatible pair. Unpinned, the AdkApp
# template inside aiplatform calls session methods synchronously while newer
# google-adk made them async → "'coroutine' object has no attribute 'id'"
# at runtime. Same pins as the team's reference deployment script.
agent_requirements = [
    "google-cloud-aiplatform[agent_engines,adk]==1.148.1",
    "google-adk==1.31.1",
    "a2a-sdk>=0.3.4,<0.4",
    "python-dotenv>=1.0.0",
    "google-cloud-secret-manager",
    "google-cloud-storage",
    "cloudpickle",
    "pydantic",
]

if agent:
    print("Updating the existing agent...")
    remote_app = agent_engines.update(
        resource_name=agent.resource_name,
        display_name=agent.display_name,
        agent_engine=app,
        description=AGENT_DESCRIPTION,
        requirements=agent_requirements,
        extra_packages=["./agent"],
        env_vars=agent_env_vars,
    )
    print(f"=======> Success! Agent updated. Resource name is: {remote_app.resource_name}.")
else:
    print("Creating a new agent...")
    remote_app = agent_engines.create(
        agent_engine=app,
        requirements=agent_requirements,
        display_name=AGENT_DISPLAY_NAME,
        description=AGENT_DESCRIPTION,
        extra_packages=["./agent"],
        env_vars=agent_env_vars,
    )
    print(f"=======> Success! Agent deployed. Resource name is: {remote_app.resource_name}.")
