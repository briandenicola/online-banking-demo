FROM python:3.11-slim

WORKDIR /app

COPY ./src/budget-service/app ./app
COPY ./src/budget-service/pyproject.toml ./

RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-dotenv \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-requests

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]