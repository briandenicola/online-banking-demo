import asyncio
import os

import structlog
from fastapi import FastAPI

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from app.cosmos_repository import CosmosDBApplicationRepository
from app.redis_client import create_redis_client
from app.repository import InMemoryApplicationRepository

logger = structlog.get_logger("account-opening-service")


def _allow_inmemory_on_cosmos_failure() -> bool:
    return os.getenv("ALLOW_INMEMORY_ON_COSMOS_FAILURE", "").strip().lower() in {"1", "true", "yes"}


async def lifespan(app: FastAPI):
    cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
    allow_inmemory_fallback = _allow_inmemory_on_cosmos_failure()

    if cosmos_endpoint and cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT":
        try:
            from azure.cosmos import CosmosClient
            from azure.cosmos.exceptions import CosmosHttpResponseError

            credential = DefaultAzureCredential()
            cosmos_client = await asyncio.to_thread(CosmosClient, cosmos_endpoint, credential=credential)
            db = cosmos_client.get_database_client("BankingDemo")
            container = db.get_container_client("account-applications")
            app.state.repository = CosmosDBApplicationRepository(container)
            app.state.repository_mode = "cosmos"
            logger.info("Using Cosmos DB repository", endpoint=cosmos_endpoint)
        except CosmosHttpResponseError as exc:
            if allow_inmemory_fallback:
                logger.warning(
                    "Cosmos DB request failed, falling back to in-memory (override enabled)",
                    error=str(exc),
                )
                app.state.repository = InMemoryApplicationRepository()
                app.state.repository_mode = "memory"
            else:
                logger.error("Cosmos DB initialization failed — aborting startup", error=str(exc))
                raise
        except (ConnectionError, OSError) as exc:
            if allow_inmemory_fallback:
                logger.warning(
                    "Cosmos DB unreachable, falling back to in-memory (override enabled)",
                    error=str(exc),
                )
                app.state.repository = InMemoryApplicationRepository()
                app.state.repository_mode = "memory"
            else:
                logger.error("Cosmos DB network error — aborting startup", error=str(exc))
                raise
        except Exception as exc:
            if allow_inmemory_fallback:
                logger.warning(
                    "Unexpected Cosmos DB init error, falling back to in-memory (override enabled)",
                    error=str(exc),
                )
                app.state.repository = InMemoryApplicationRepository()
                app.state.repository_mode = "memory"
            else:
                logger.error("Unexpected Cosmos DB init failure — aborting startup", error=str(exc))
                raise
    else:
        logger.warning("COSMOS_DB_ENDPOINT not set — using in-memory repository")
        app.state.repository = InMemoryApplicationRepository()
        app.state.repository_mode = "memory"

    app.state.redis = await create_redis_client()

    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if storage_account_name:
        credential = DefaultAzureCredential()
        account_url = f"https://{storage_account_name}.blob.core.windows.net"
        app.state.blob_service_client = BlobServiceClient(account_url, credential=credential)
    else:
        logger.warning("AZURE_STORAGE_ACCOUNT_NAME not set — blob uploads disabled")
        app.state.blob_service_client = None

    yield
    redis_client = app.state.redis
    if redis_client:
        close_result = redis_client.close()
        if asyncio.iscoroutine(close_result):
            await close_result
