from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import redis.asyncio as redis
import structlog

from .agents import (
    ComplianceCheckConsumer,
    DocumentExtractionConsumer,
    IdentityVerificationConsumer,
    ProvisioningConsumer,
)
from .repository import InMemoryApplicationRepository
from .state_machine import ApplicationStateMachine

logger = structlog.get_logger("account-opening-worker")


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _parse_redis_connection_string(conn_str: str) -> dict:
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


async def _create_redis_client() -> redis.Redis | None:
    conn_str = os.getenv("REDIS__CONNECTIONSTRING", "redis:6379")
    parsed = _parse_redis_connection_string(conn_str)
    kwargs = {
        "host": parsed["host"],
        "port": parsed["port"],
        "decode_responses": True,
    }
    if parsed["password"]:
        kwargs["password"] = parsed["password"]
    if parsed["ssl"]:
        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = None

    client = redis.Redis(**kwargs)
    try:
        await client.ping()
        logger.info("Connected to Redis", host=parsed["host"], port=parsed["port"])
        return client
    except Exception as exc:
        logger.error("Redis unavailable", error=str(exc))
        return None


async def main() -> int:
    _configure_logging()

    try:
        from agent_framework_foundry import FoundryAgent
    except ImportError:
        logger.error("agent-framework-foundry is not installed")
        return 1

    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        logger.error("azure-identity is not installed")
        return 1

    foundry_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    foundry_model = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")
    cus_endpoint = os.getenv("CUS_ENDPOINT")

    if not foundry_endpoint:
        logger.error("FOUNDRY_PROJECT_ENDPOINT is not set")
        return 1
    if not cus_endpoint:
        logger.error("CUS_ENDPOINT is not set")
        return 1

    credential = DefaultAzureCredential()
    try:
        token = credential.get_token("https://ai.azure.com/.default")
        logger.info("Azure credential acquired", expires=token.expires_on)
    except Exception as exc:
        logger.error("Failed to acquire Azure credential", error=str(exc))
        return 1

    try:
        connectivity_agent = FoundryAgent(
            project_endpoint=foundry_endpoint.rstrip("/"),
            credential=credential,
            agent_name="identity-verifier",
            agent_version="1",
            description="Foundry connectivity check agent",
            instructions="Respond with JSON: {\"status\": \"ok\"}",
        )
        session = connectivity_agent.create_session()
        response = await connectivity_agent.run("ping", session=session)
        if response is None:
            raise RuntimeError("Foundry agent returned empty response")
        logger.info("Foundry connectivity verified")
    except Exception as exc:
        logger.error("Foundry connectivity check failed", error=str(exc))
        return 1

    redis_client = await _create_redis_client()
    if not redis_client:
        return 1

    repository = InMemoryApplicationRepository()
    state_machine = ApplicationStateMachine()

    worker_id = os.getenv("HOSTNAME", "account-opening-worker")
    consumers = [
        DocumentExtractionConsumer(
            redis_client,
            repository=repository,
            state_machine=state_machine,
            consumer_name=f"{worker_id}-document-extraction",
            cus_endpoint=cus_endpoint,
        ),
        IdentityVerificationConsumer(
            redis_client,
            repository=repository,
            state_machine=state_machine,
            consumer_name=f"{worker_id}-identity-verification",
            foundry_endpoint=foundry_endpoint,
            foundry_model=foundry_model,
            credential=credential,
        ),
        ComplianceCheckConsumer(
            redis_client,
            repository=repository,
            state_machine=state_machine,
            consumer_name=f"{worker_id}-compliance",
            foundry_endpoint=foundry_endpoint,
            foundry_model=foundry_model,
            credential=credential,
        ),
        ProvisioningConsumer(
            redis_client,
            repository=repository,
            state_machine=state_machine,
            consumer_name=f"{worker_id}-provisioning",
            foundry_endpoint=foundry_endpoint,
            foundry_model=foundry_model,
            credential=credential,
        ),
    ]

    for consumer in consumers:
        await consumer.setup()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [asyncio.create_task(consumer.run(stop_event)) for consumer in consumers]
    logger.info("Account-opening agents started", count=len(tasks))

    await stop_event.wait()

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    close_result = redis_client.close()
    if asyncio.iscoroutine(close_result):
        await close_result

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
