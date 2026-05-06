# Decision: Structured Logging & OpenTelemetry Observability

**Author:** Basher (Backend Dev)
**Date:** 2026-05-06
**Status:** Implemented
**Branch:** squad/observability

## Context

The system had no structured logging and telemetry was misconfigured (hardcoded App Insights endpoints, wrong env var names). Debugging cross-service issues required manual log correlation. No distributed tracing was functional.

## Decision

Implement a layered observability stack:

1. **Structured JSON logging** — Serilog (.NET) and structlog (Python) emit machine-parseable JSON logs
2. **Correlation ID propagation** — nginx generates X-Correlation-ID at the gateway; all services read/propagate it
3. **OpenTelemetry OTLP tracing** — Configured via OTEL_EXPORTER_OTLP_ENDPOINT env var; disabled when empty
4. **Optional Jaeger** — Commented-out docker-compose service for local trace visualization

## Alternatives Considered

- **Application Insights SDK directly** — Rejected: vendor lock-in, requires Azure subscription for local dev
- **Zipkin** — Rejected: Jaeger has better UI and OTLP native support
- **Fluentd/ELK for log aggregation** — Deferred: structured JSON logs are ready for any collector

## Consequences

- All services log structured JSON — ready for any log aggregator (Azure Monitor, ELK, Loki)
- Correlation IDs flow end-to-end through nginx → services → downstream calls
- Zero cost when disabled (empty OTLP endpoint = no export)
- 1 new shared .NET project dependency added to all C# services
- 1 new Python dependency (structlog) added to all Python services
- To enable tracing locally: uncomment Jaeger in docker-compose + set OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
