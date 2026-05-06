# Decision: Structured Logging & OpenTelemetry Observability

**Author:** Basher (Backend Dev)  
**Date:** 2026-05-06  
**Status:** Implemented  
**Branch:** squad/observability

## Context

Telemetry was misconfigured (hardcoded App Insights endpoints). No structured logging. No correlation ID propagation. Cross-service debugging required manual log correlation.

## Decision

1. **Structured JSON logging** — Serilog (.NET) + structlog (Python)
2. **Correlation ID propagation** — nginx generates X-Correlation-ID; all services read/propagate
3. **OpenTelemetry OTLP tracing** — Configured via OTEL_EXPORTER_OTLP_ENDPOINT; disabled when empty
4. **Optional Jaeger** — Commented-out in docker-compose for local trace viewing

## Consequences

- All services emit structured JSON logs with correlation IDs
- Distributed tracing activatable by setting one env var
- Zero cost when disabled (no export when endpoint is empty)
- To enable: uncomment Jaeger + set OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
