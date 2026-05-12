"""
Shared Redis client factory for account-opening-service.

Uses Entra ID token-based auth when running in Azure (AZURE_CLIENT_ID set),
falls back to plain Redis for local dev.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import ssl

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger("account-opening-redis")

REDIS_SCOPE = "acca5fbb-b7e4-4009-81f1-37e38fd66d78/.default"
TOKEN_REFRESH_SECONDS = 20 * 60  # 20 minutes


def _parse_redis_connection_string(conn_str: str) -> dict:
    """Parse a StackExchange.Redis-style connection string."""
    result = {"host": "redis", "port": 6379, "ssl": False, "password": None}
    parts = [p.strip() for p in conn_str.split(",") if p.strip()]
    for index, part in enumerate(parts):
        if index == 0:
            if ":" in part and "=" not in part:
                host, port_str = part.rsplit(":", 1)
                result["host"] = host
                if port_str.isdigit():
                    result["port"] = int(port_str)
            else:
                result["host"] = part
            continue
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "ssl" and value.lower() == "true":
            result["ssl"] = True
        if key == "password":
            result["password"] = value
    return result


def _extract_oid_from_token(token: str) -> str:
    """Extract the OID claim from a JWT access token."""
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    payload = parts[1]
    # Add base64 padding if needed
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    try:
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        return claims.get("oid", "")
    except Exception as exc:
        logger.warning("Failed to decode JWT payload", error=str(exc))
        return ""


async def _refresh_token_loop(
    cluster_client: aioredis.RedisCluster,
    credential,
) -> None:
    """Periodically refresh the Entra ID token on the Redis cluster connection."""
    while True:
        await asyncio.sleep(TOKEN_REFRESH_SECONDS)
        try:
            token_response = credential.get_token(REDIS_SCOPE)
            new_token = token_response.token
            oid = _extract_oid_from_token(new_token)
            # Re-authenticate every node in the cluster
            await cluster_client.execute_command("AUTH", oid, new_token)
            logger.info("Redis token refreshed")
        except Exception as exc:
            logger.warning("Failed to refresh Redis token", error=str(exc))


async def create_redis_client() -> aioredis.Redis | aioredis.RedisCluster | None:
    """
    Create and return a connected Redis client.

    In Azure (AZURE_CLIENT_ID set): uses RedisCluster with Entra ID auth.
    Locally: uses plain Redis client from connection string.
    """
    conn_str = os.getenv("REDIS__CONNECTIONSTRING", "redis:6379")
    parsed = _parse_redis_connection_string(conn_str)

    if os.getenv("AZURE_CLIENT_ID"):
        return await _create_entra_redis_client(parsed)

    return await _create_local_redis_client(parsed)


async def _create_entra_redis_client(parsed: dict) -> aioredis.RedisCluster | None:
    """Create a RedisCluster client using Entra ID token-based auth."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        logger.error("azure-identity is not installed")
        return None

    try:
        credential = DefaultAzureCredential()
        token_response = credential.get_token(REDIS_SCOPE)
        token = token_response.token
        oid = _extract_oid_from_token(token)
        logger.info("Entra ID token acquired for Redis", oid=oid)
    except Exception as exc:
        logger.error("Failed to acquire Entra ID token for Redis", error=str(exc))
        return None

    try:
        client = aioredis.RedisCluster(
            host=parsed["host"],
            port=parsed["port"],
            username=oid,
            password=token,
            ssl=True,
            ssl_cert_reqs=None,
        )
        await client.ping()
        logger.info(
            "Connected to Azure Managed Redis (cluster)",
            host=parsed["host"],
            port=parsed["port"],
        )

        # Start background token refresh
        asyncio.create_task(_refresh_token_loop(client, credential))

        return client
    except Exception as exc:
        logger.error("Redis cluster connection failed", error=str(exc))
        return None


async def _create_local_redis_client(parsed: dict) -> aioredis.Redis | None:
    """Create a plain Redis client for local development."""
    kwargs: dict = {
        "host": parsed["host"],
        "port": parsed["port"],
        "decode_responses": True,
    }
    if parsed["password"]:
        kwargs["password"] = parsed["password"]
    if parsed["ssl"]:
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = None

    client = aioredis.Redis(**kwargs)
    try:
        await client.ping()
        logger.info("Connected to Redis (local)", host=parsed["host"], port=parsed["port"])
        return client
    except Exception as exc:
        logger.warning("Redis unavailable", error=str(exc))
        return None
