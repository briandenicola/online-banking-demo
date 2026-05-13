import asyncio
import os

import structlog
from typing import Optional

from app.config import DefaultAzureCredential, EmbeddingsClient

logger = structlog.get_logger("budget-service")


async def startup_event(embeddings_client: Optional[EmbeddingsClient]) -> None:
    """Initialize event processor and AI client with validation."""
    # Validate Entra ID token acquisition for Azure OpenAI (Foundry) Embeddings
    if DefaultAzureCredential and os.getenv("AZURE_OPENAI_ENDPOINT"):
        logger.info("=" * 50)
        logger.info("Validating Azure OpenAI (Foundry) Embeddings connectivity...")
        try:
            credential = DefaultAzureCredential()
            token = await asyncio.to_thread(credential.get_token, "https://cognitiveservices.azure.com/.default")
            logger.info(f"✅ Azure OpenAI token acquired (expires {token.expires_on})")

            # Test embeddings connectivity with a simple ping
            if embeddings_client:
                try:
                    test_response = await asyncio.to_thread(
                        embeddings_client.embed,
                        model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
                        input=["ping"],
                    )
                    logger.info(
                        "✅ Azure OpenAI Embeddings connectivity verified - "
                        f"{len(test_response.data[0].embedding)} dimensions"
                    )
                except Exception as ping_ex:
                    logger.warning(f"⚠️ OpenAI Embeddings ping failed: {ping_ex}")
        except Exception as ex:
            logger.error(f"❌ Azure OpenAI token acquisition FAILED: {ex}")
            logger.error(
                "Ensure AZURE_OPENAI_ENDPOINT is set and Managed Identity/Service Principal "
                "has Cognitive Services OpenAI User role"
            )
