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


async def lifespan(app: FastAPI):
    cosmos_endpoint = os.getenv("COSMOS_DB_ENDPOINT")
    is_production = bool(os.getenv("AZURE_CLIENT_ID"))
    if cosmos_endpoint and cosmos_endpoint != "REPLACE_WITH_COSMOS_ENDPOINT":
        try:
            from azure.cosmos import CosmosClient
            from azure.cosmos.exceptions import CosmosHttpResponseError

            credential = DefaultAzureCredential()
            cosmos_client = await asyncio.to_thread(CosmosClient, cosmos_endpoint, credential=credential)
            db = cosmos_client.get_database_client("BankingDemo")
            container = db.get_container_client("account-applications")
            app.state.repository = CosmosDBApplicationRepository(container)
            logger.info("Using Cosmos DB repository", endpoint=cosmos_endpoint)
        except CosmosHttpResponseError as exc:
            if is_production:
                logger.error("Cosmos DB initialization failed in production — aborting startup", error=str(exc))
                raise
            logger.warning("Cosmos DB request failed, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
        except (ConnectionError, OSError) as exc:
            if is_production:
                logger.error("Cosmos DB network error in production — aborting startup", error=str(exc))
                raise
            logger.warning("Cosmos DB unreachable, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
        except Exception as exc:
            if is_production:
                logger.error("Unexpected Cosmos DB init failure in production — aborting startup", error=str(exc))
                raise
            logger.warning("Unexpected Cosmos DB init error, falling back to in-memory", error=str(exc))
            app.state.repository = InMemoryApplicationRepository()
    else:
        logger.warning("COSMOS_DB_ENDPOINT not set — using in-memory repository")
        app.state.repository = InMemoryApplicationRepository()

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
