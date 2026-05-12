from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import structlog

from .agents import (
    ComplianceCheckConsumer,
    DocumentExtractionConsumer,
    IdentityVerificationConsumer,
    ProvisioningConsumer,
)
from .redis_client import create_redis_client
from .repository import InMemoryApplicationRepository
from .cosmos_repository import CosmosDBApplicationRepository
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

    redis_client = await create_redis_client()
    if not redis_client:
        return 1

    cosmos_endpoint = os.getenv("CosmosDb__Endpoint")
    if cosmos_endpoint and cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT":
        try:
            from azure.cosmos import CosmosClient

            cosmos_client = CosmosClient(cosmos_endpoint, credential=credential)
            db = cosmos_client.get_database_client("BankingDemo")
            container = db.get_container_client("account-applications")
            repository = CosmosDBApplicationRepository(container)
            logger.info("Worker using Cosmos DB repository", endpoint=cosmos_endpoint)
        except Exception as exc:
            logger.error("Worker failed to init Cosmos DB", error=str(exc))
            return 1
    else:
        logger.error("CosmosDb__Endpoint not set — worker requires Cosmos DB for shared state")
        return 1

    state_machine = ApplicationStateMachine()

    # BlobServiceClient for document extraction to download blobs for CUS
    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if storage_account_name:
        from azure.storage.blob import BlobServiceClient
        blob_account_url = f"https://{storage_account_name}.blob.core.windows.net"
        blob_service_client = BlobServiceClient(blob_account_url, credential=credential)
        logger.info("Blob service client initialized", account=storage_account_name)
    else:
        logger.error("AZURE_STORAGE_ACCOUNT_NAME not set — required for document extraction")
        return 1

    worker_id = os.getenv("HOSTNAME", "account-opening-worker")
    consumers = [
        DocumentExtractionConsumer(
            redis_client,
            repository=repository,
            state_machine=state_machine,
            consumer_name=f"{worker_id}-document-extraction",
            cus_endpoint=cus_endpoint,
            blob_service_client=blob_service_client,
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
