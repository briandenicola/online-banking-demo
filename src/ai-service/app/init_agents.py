"""
Init-container script: provision Foundry prompt-agents before the main
ai-service starts.

Idempotent — compares each agent's latest version against the instructions
below and only creates a new version when the text has changed.

The runtime clients reference these agents WITHOUT pinning a version, so the
newest version wins. This matters because the Responses API rejects an
``instructions`` field whenever an ``agent_reference`` is present, which means
the agent definition here is the only channel for the system prompt.

Exits 0 on success, 1 on any failure.

Usage:
    python -m app.init_agents
"""

import json
import logging
import os
import sys

import httpx
from azure.identity import DefaultAzureCredential

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("init_agents")

API_VERSION = "v1"
TOKEN_SCOPE = "https://ai.azure.com/.default"

# ---------------------------------------------------------------------------
# Agent definitions (must match what FoundryAgent expects at runtime)
# ---------------------------------------------------------------------------
AGENTS: list[dict] = [
    {
        "agent_name": "risk-assessor",
        "description": "Financial transaction risk scoring agent",
        "definition": {
            "kind": "prompt",
            "model": None,  # filled at runtime from FOUNDRY_MODEL
            "instructions": (
                "You are a financial security expert at a major bank. "
                "Your job is to assess transaction risk.\n\n"
                "Analyze each transaction and provide a risk assessment. Consider:\n"
                "- Transaction amount relative to typical banking activity\n"
                "- Transaction type and whether it matches expected patterns\n"
                "- Description for suspicious keywords or patterns\n"
                "- Category context\n\n"
                "Risk scoring guidelines:\n"
                "- 0.0-0.3: Normal, low-risk transaction (routine purchases, small transfers)\n"
                "- 0.3-0.5: Slightly elevated risk (larger than typical, unusual category)\n"
                "- 0.5-0.7: Moderate risk (significantly unusual amount or pattern)\n"
                "- 0.7-0.9: High risk (suspicious pattern, very large amount, unusual destination)\n"
                "- 0.9-1.0: Critical risk (clear fraud indicators, impossible patterns)\n\n"
                "Examples:\n"
                '- $25 grocery purchase → {"riskScore": 0.05, "explanation": "Routine small purchase", "flags": []}\n'
                '- $500 transfer to known account → {"riskScore": 0.15, "explanation": "Normal transfer amount", "flags": []}\n'
                '- $5,000 transfer to new account → {"riskScore": 0.55, "explanation": "Large transfer — elevated due to amount", "flags": ["large_transfer"]}\n'
                '- $15,000 wire at unusual hours → {"riskScore": 0.85, "explanation": "Very large amount with unusual timing", "flags": ["large_amount", "unusual_time"]}\n\n'
                "Respond with ONLY a JSON object (no markdown, no text outside JSON):\n"
                '{"riskScore": <float 0.0-1.0>, "explanation": "<1-2 sentence explanation>", "flags": ["<flag1>", ...]}'
            ),
        },
    },
    {
        "agent_name": "transaction-categorizer",
        "description": "Financial transaction categorization agent",
        "definition": {
            "kind": "prompt",
            "model": None,
            "instructions": (
                "You are a financial transaction categorizer. "
                "Your ONLY job is to assign a category to a transaction.\n\n"
                "Choose the single best category from common banking categories:\n"
                "- Groceries\n- Dining & Restaurants\n- Entertainment\n"
                "- Transportation\n- Utilities\n- Healthcare\n- Shopping\n"
                "- Travel\n- Income\n- Transfer\n- Subscription\n"
                "- Education\n- Housing\n- Insurance\n- Savings\n"
                "- Cash Withdrawal\n- Fees & Charges\n- Other\n\n"
                "If the user has provided custom categories, prefer those when they are a good fit.\n\n"
                "Respond with ONLY a JSON object (no markdown, no text outside JSON):\n"
                '{"category": "<category name>", "confidence": <float 0.0-1.0>, "reasoning": "<brief reason>"}'
            ),
        },
    },
]


def _get_auth_header(credential: DefaultAzureCredential) -> dict[str, str]:
    token = credential.get_token(TOKEN_SCOPE)
    return {"Authorization": f"Bearer {token.token}"}


def _latest_instructions(
    client: httpx.Client,
    endpoint: str,
    agent_name: str,
    headers: dict[str, str],
) -> str | None:
    """Return the instructions on the agent's highest-numbered version.

    Returns None when the agent does not exist yet, or exists with no versions.
    """
    url = f"{endpoint}/agents/{agent_name}/versions"
    resp = client.get(url, params={"api-version": API_VERSION}, headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    versions = resp.json().get("data") or []
    if not versions:
        return None

    def _key(item: dict) -> int:
        try:
            return int(item.get("version"))
        except (TypeError, ValueError):
            return -1

    latest = max(versions, key=_key)
    return (latest.get("definition") or {}).get("instructions")


def _create_agent(
    client: httpx.Client,
    endpoint: str,
    agent_name: str,
    agent_spec: dict,
    headers: dict[str, str],
) -> None:
    url = f"{endpoint}/agents/{agent_name}/versions"
    body = {
        "description": agent_spec["description"],
        "definition": agent_spec["definition"],
    }
    resp = client.post(
        url,
        params={"api-version": API_VERSION},
        headers={**headers, "Content-Type": "application/json"},
        content=json.dumps(body),
    )
    resp.raise_for_status()


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
        headers = _get_auth_header(credential)
        logger.info("✅ Azure credential acquired")
    except Exception as exc:
        logger.error(f"❌ Failed to acquire Azure credential: {exc}")
        return 1

    errors = 0
    with httpx.Client(timeout=30.0) as client:
        for spec in AGENTS:
            name = spec["agent_name"]
            spec["definition"]["model"] = model
            instructions = spec["definition"]["instructions"]

            try:
                current = _latest_instructions(client, endpoint, name, headers)
                if current is not None and current.strip() == instructions.strip():
                    logger.info(f"✅ Agent '{name}' is already up to date")
                    continue

                action = "creating" if current is None else "updating (prompt changed)"
                logger.info(f"Agent '{name}': {action} ...")
                _create_agent(client, endpoint, name, spec, headers)
                logger.info(f"✅ Agent '{name}' provisioned successfully")
            except httpx.HTTPStatusError as exc:
                logger.error(
                    f"❌ Failed to provision agent '{name}': "
                    f"{exc.response.status_code} — {exc.response.text}"
                )
                errors += 1
            except Exception as exc:
                logger.error(f"❌ Unexpected error provisioning agent '{name}': {exc}")
                errors += 1

    if errors:
        logger.error(f"Agent provisioning completed with {errors} error(s)")
        return 1

    logger.info("✅ All agents provisioned — init complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
