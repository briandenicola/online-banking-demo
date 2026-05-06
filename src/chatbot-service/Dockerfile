FROM python:3.11-slim

WORKDIR /app

COPY ./src/chatbot-service/app ./app
COPY ./src/chatbot-service/pyproject.toml ./

RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-dotenv structlog \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-requests \
    opentelemetry-instrumentation-httpx \
    azure-ai-agents azure-identity

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]