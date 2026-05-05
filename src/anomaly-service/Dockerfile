FROM python:3.11-slim

WORKDIR /app

COPY ./src/anomaly-service/app ./app
COPY ./src/anomaly-service/pyproject.toml ./

RUN pip install --no-cache-dir \
    fastapi uvicorn httpx pydantic python-dotenv \
    numpy scikit-learn \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]