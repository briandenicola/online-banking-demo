FROM python:3.11-slim

WORKDIR /app

COPY ./app ./app
COPY ./pyproject.toml ./

RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-dotenv structlog redis \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]