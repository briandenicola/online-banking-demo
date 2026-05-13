import json
import os
from contextvars import ContextVar
from typing import Annotated

import httpx
import structlog
from pydantic import Field

from app.config import tool

logger = structlog.get_logger("chatbot-service")

# --- Agent Framework tool functions ---
BUDGET_SERVICE_URL = os.getenv("BUDGET_SERVICE_URL", "http://budget-service:8003")
TRANSACTION_SERVICE_URL = os.getenv("TRANSACTION_SERVICE_URL", "http://transaction-service:8080")
ACCOUNT_SERVICE_URL = os.getenv("ACCOUNT_SERVICE_URL", "http://account-service:8080")

# ContextVar to pass the user's JWT to tool functions
_current_auth_token: ContextVar[str] = ContextVar("_current_auth_token", default="")


def set_current_auth_token(token: str) -> None:
    _current_auth_token.set(token)


def _mask_account_number(account_number: str | None) -> str:
    """Mask account number to show only last 4 digits for security."""
    if not account_number or len(account_number) < 4:
        return "****"
    return f"****{account_number[-4:]}"


def _sanitize_account_data(accounts: list[dict]) -> list[dict]:
    """Sanitize account data to mask sensitive fields before passing to agent."""
    sanitized = []
    for acct in accounts:
        sanitized.append({
            "id": acct.get("id", ""),
            "accountNumber": _mask_account_number(acct.get("accountNumber", "")),
            "type": acct.get("type", ""),
            "balance": acct.get("balance", 0),
            "currency": acct.get("currency", "USD"),
        })
    return sanitized


def _sanitize_transaction_description(description: str | None) -> str:
    """Remove or mask potentially sensitive information from transaction descriptions."""
    if not description:
        return ""

    # Remove email addresses
    import re
    description = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', description)

    # Remove phone numbers
    description = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', description)

    # Keep description length reasonable to prevent context overflow
    if len(description) > 100:
        description = description[:97] + "..."

    return description


@tool(approval_mode="never_require")
def get_budget_insights(
    period: Annotated[str, Field(description="Time period (e.g. '7d', '30d')")] = "30d",
) -> str:
    """Get budget insights including spending breakdown and savings rate for the authenticated user."""
    token = _current_auth_token.get("")
    if not token:
        return json.dumps({"error": "No auth token available to fetch budget insights"})
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = httpx.get(f"{BUDGET_SERVICE_URL}/insights/me?period={period}", headers=headers, timeout=10.0)
        if response.is_success:
            return json.dumps(response.json())
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to get budget insights: {e}")
    return json.dumps({"error": "Unable to retrieve budget insights"})


@tool(approval_mode="never_require")
def get_spending_pattern() -> str:
    """Get recent spending patterns and trends for the authenticated user over the last 7 days."""
    token = _current_auth_token.get("")
    if not token:
        return json.dumps({"error": "No auth token available to fetch spending patterns"})
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = httpx.get(f"{BUDGET_SERVICE_URL}/insights/me?period=7d", headers=headers, timeout=10.0)
        if response.is_success:
            return json.dumps(response.json())
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to get spending patterns: {e}")
    return json.dumps({"error": "Unable to retrieve spending patterns"})


@tool(approval_mode="never_require")
def analyze_transaction(
    description: Annotated[str, Field(description="Transaction description text")],
    amount: Annotated[float, Field(description="Transaction amount in dollars")],
) -> str:
    """Analyze and categorize a transaction for budgeting purposes."""
    try:
        response = httpx.post(f"{BUDGET_SERVICE_URL}/categorize", params={"description": description}, timeout=10.0)
        if response.is_success:
            data = response.json()
            return json.dumps({
                "description": description,
                "amount": amount,
                "suggested_category": data.get("category", "Uncategorized"),
                "note": "Transaction analyzed successfully",
            })
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to analyze transaction: {e}")
    return json.dumps({"error": "Unable to analyze transaction"})


@tool(approval_mode="never_require")
def get_user_transactions() -> str:
    """Get the authenticated user's recent transactions from the transaction service."""
    token = _current_auth_token.get("")
    if not token:
        return json.dumps({"error": "No auth token available to fetch transactions"})
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = httpx.get(f"{TRANSACTION_SERVICE_URL}/api/transactions/my", headers=headers, timeout=10.0)
        if response.is_success:
            txns = response.json()
            # Summarize for the agent — limit to recent 20 to keep context manageable
            summary = []
            for tx in txns[:20]:
                # Sanitize transaction description to remove sensitive information
                sanitized_desc = _sanitize_transaction_description(tx.get("description", ""))
                summary.append({
                    "id": tx.get("id", ""),
                    "amount": tx.get("amount", 0),
                    "type": tx.get("type", ""),
                    "description": sanitized_desc,
                    "category": tx.get("category", ""),
                    "riskScore": tx.get("riskScore", 0),
                    "createdAt": tx.get("createdAt", ""),
                })
            return json.dumps({"transactions": summary, "total": len(txns)})
        else:
            logger.warning(f"Transaction service returned {response.status_code}: {response.text[:200]}")
            return json.dumps({"error": f"Account service returned {response.status_code}"})
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to get transactions: {e}")
    return json.dumps({"error": "Unable to retrieve transactions"})


@tool(approval_mode="never_require")
def get_user_accounts() -> str:
    """Get the authenticated user's bank accounts including balances."""
    token = _current_auth_token.get("")
    if not token:
        return json.dumps({"error": "No auth token available to fetch accounts"})
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = httpx.get(f"{ACCOUNT_SERVICE_URL}/api/accounts/my", headers=headers, timeout=10.0)
        if response.is_success:
            accounts = response.json()
            # Sanitize account data before passing to agent
            sanitized_accounts = _sanitize_account_data(accounts)
            return json.dumps({"accounts": sanitized_accounts})
        else:
            logger.warning(f"Account service returned {response.status_code}: {response.text[:200]}")
            return json.dumps({"error": f"Account service returned {response.status_code}"})
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Failed to get accounts: {e}")
    return json.dumps({"error": "Unable to retrieve accounts"})
