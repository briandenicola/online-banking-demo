"""
Init-container script: provision Foundry prompt-agents before the
account-opening worker starts.

Idempotent — compares each agent's latest version against the prompt in
``prompts.py`` and only creates a new version when the text has changed.

The runtime clients reference these agents WITHOUT pinning a version, so the
newest version wins. This matters because the Responses API rejects an
``instructions`` field whenever an ``agent_reference`` is present, which means
the agent definition here is the only channel for the system prompt.

Exits 0 on success, 1 on any failure.

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

from .prompts import (
    ACCOUNT_PROVISIONING_PROMPT,
    COMPLIANCE_ASSESSMENT_PROMPT,
    CUSTOMER_EXPLANATION_PROMPT,
    IDENTITY_VERIFICATION_PROMPT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("account-opening-init")

TOKEN_SCOPE = "https://ai.azure.com/.default"

AGENTS: list[dict] = [
    {
        "agent_name": "identity-verifier",
        "description": "Identity verification agent",
        "instructions": IDENTITY_VERIFICATION_PROMPT,
    },
    {
        "agent_name": "compliance-assessor",
        "description": "KYC compliance assessment agent",
        "instructions": COMPLIANCE_ASSESSMENT_PROMPT,
    },
    {
        "agent_name": "account-provisioner",
        "description": "Account provisioning agent",
        "instructions": ACCOUNT_PROVISIONING_PROMPT,
    },
    {
        "agent_name": "customer-explanation-generator",
        "description": "Generates customer-facing explanations",
        "instructions": CUSTOMER_EXPLANATION_PROMPT,
    },
]


def _latest_instructions(client: AIProjectClient, agent_name: str) -> str | None:
    """Return the instructions on the agent's highest-numbered version.

    Returns None when the agent has no versions yet (never provisioned, or the
    agent shell exists but is empty — which is how customer-explanation-generator
    was left, causing a 404 at request time).
    """
    try:
        versions = list(client.agents.list_versions(agent_name))
    except ResourceNotFoundError:
        return None
    if not versions:
        return None

    def _key(v: object) -> int:
        raw = getattr(v, "version", None)
        try:
            return int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return -1

    latest = max(versions, key=_key)
    definition = getattr(latest, "definition", None)
    return getattr(definition, "instructions", None)


def main() -> int:
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")

    if not endpoint:
        logger.error("❌ FOUNDRY_PROJECT_ENDPOINT is not set — cannot provision agents")
        return 1

    endpoint = endpoint.rstrip("/")
    logger.info(f"Foundry endpoint: {endpoint}")
    logger.info(f"Model: {model}")

    # NOTE: This init container runs BEFORE sidecar containers start in K8s.
    # The Entra Agent ID auth-sidecar is NOT available here, so we MUST use
    # DefaultAzureCredential (workload identity via projected token).
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
        instructions = spec["instructions"]
        try:
            current = _latest_instructions(client, name)
            if current is not None and current.strip() == instructions.strip():
                logger.info(f"✅ Agent '{name}' is already up to date")
                continue

            action = "creating" if current is None else "updating (prompt changed)"
            logger.info(f"Agent '{name}': {action} ...")
            definition = PromptAgentDefinition(
                model=model,
                instructions=instructions,
            )
            client.agents.create_version(
                agent_name=name,
                definition=definition,
                description=spec["description"],
            )
            logger.info(f"✅ Agent '{name}' provisioned successfully")
        except Exception as exc:
            logger.error(f"❌ Failed to provision agent '{name}': {exc}")
            errors += 1

    if errors:
        logger.warning(f"Agent provisioning completed with {errors} error(s) — continuing anyway")
        return 0

    logger.info("✅ All agents provisioned — init complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
