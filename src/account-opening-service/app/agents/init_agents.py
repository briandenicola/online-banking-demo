"""
Init-container script: provision Foundry prompt-agents before the
account-opening worker starts.

Idempotent — checks whether each agent version already exists and only
creates it when missing. Exits 0 on success, 1 on any failure.

Usage:
    python -m app.agents.init_agents
"""

import logging
import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("account-opening-init")

TOKEN_SCOPE = "https://ai.azure.com/.default"

AGENTS: list[dict] = [
    {
        "agent_name": "identity-verifier",
        "agent_version": "1",
        "description": "Identity verification agent",
        "instructions": (
            "You are a bank identity verification agent. Compare extracted "
            "document data against the application form data and determine if "
            "the identity is verified. Return ONLY JSON with fields: "
            "verified, confidence, flags, reasoning."
        ),
    },
    {
        "agent_name": "compliance-assessor",
        "agent_version": "1",
        "description": "KYC compliance assessment agent",
        "instructions": (
            "You are a KYC compliance officer. Evaluate the customer's risk "
            "tier and KYC status using identity verification, income, "
            "employment, and compliance rules. Return ONLY JSON with fields: "
            "kycStatus, riskTier, confidence, flags, reasoning."
        ),
    },
    {
        "agent_name": "account-provisioner",
        "agent_version": "1",
        "description": "Account provisioning agent",
        "instructions": (
            "You are the account provisioning orchestrator. Summarize the "
            "final decision (approved/rejected/pending_review) and reasoning "
            "based on compliance + identity results. Return ONLY JSON with "
            "fields: decision, confidence, flags, reasoning."
        ),
    },
]


def _agent_version_exists(
    client: AIProjectClient, agent_name: str, agent_version: str
) -> bool:
    try:
        client.agents.get(agent_name=agent_name, agent_version=agent_version)
        return True
    except ResourceNotFoundError:
        return False


def main() -> int:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")

    if not endpoint:
        logger.error("❌ FOUNDRY_PROJECT_ENDPOINT is not set — cannot provision agents")
        return 1

    endpoint = endpoint.rstrip("/")
    logger.info(f"Foundry endpoint: {endpoint}")
    logger.info(f"Model: {model}")

    try:
        credential = DefaultAzureCredential()
        token = credential.get_token(TOKEN_SCOPE)
        logger.info(f"✅ Azure credential acquired (expires: {token.expires_on})")
    except Exception as exc:
        logger.error(f"❌ Failed to acquire Azure credential: {exc}")
        return 1

    client = AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True)
    errors = 0

    for spec in AGENTS:
        name = spec["agent_name"]
        version = spec["agent_version"]
        try:
            if _agent_version_exists(client, name, version):
                logger.info(f"✅ Agent '{name}' v{version} already exists")
                continue

            logger.info(f"Creating agent '{name}' v{version} ...")
            definition = PromptAgentDefinition(
                model=model,
                instructions=spec["instructions"],
            )
            client.agents.create_version(
                agent_name=name,
                agent_version=version,
                definition=definition,
                description=spec["description"],
            )
            logger.info(f"✅ Agent '{name}' v{version} created successfully")
        except Exception as exc:
            logger.error(f"❌ Failed to provision agent '{name}': {exc}")
            errors += 1

    if errors:
        logger.error(f"Agent provisioning completed with {errors} error(s)")
        return 1

    logger.info("✅ All agents provisioned — init complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
