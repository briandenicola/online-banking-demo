FROM python:3.11-slim

WORKDIR /app

COPY ./app ./app
COPY ./pyproject.toml ./

RUN pip install --no-cache-dir --root-user-action=ignore \
    fastapi uvicorn httpx pydantic[email] python-dotenv structlog aiohttp \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-requests \
    opentelemetry-instrumentation-httpx \
    agent-framework-foundry azure-identity azure-cosmos

EXPOSE 8001

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]