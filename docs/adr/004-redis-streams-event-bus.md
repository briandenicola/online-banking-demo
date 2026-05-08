# ADR-004: Redis Streams as Event Bus over Dedicated Message Brokers

**Status**: Accepted  
**Date**: 2026-05  
**Author**: Brian De Nicola

## Context

The application needs asynchronous event-driven communication between services. When a transaction is recorded or a transfer completes, downstream consumers (AI risk scoring, event audit logging) must be notified without blocking the request path. Options include Redis Streams, Azure Service Bus, RabbitMQ, and Kafka.

## Decision

Use **Redis Streams** with a single `banking-events` stream and consumer groups for fan-out.

### Reasons

1. **Infrastructure consolidation** — Redis is already deployed for potential caching needs. Adding Streams reuses the same instance rather than introducing a new managed service.
2. **Consumer groups** — Redis Streams `XREADGROUP` provides built-in fan-out: the `ai-service` and `event-processor` each have their own consumer group, independently processing the same events.
3. **Simplicity** — Producers call `XADD banking-events` with a JSON payload. Consumers call `XREADGROUP` in a loop. No topic/subscription management, no schema registry, no partitioning config.
4. **Azure Managed Redis support** — Azure Managed Redis (Balanced B0) supports Streams natively. The cluster mode requires cluster-aware clients (Python `RedisCluster`, Go `redis.ClusterClient`), but StackExchange.Redis (.NET) handles it transparently.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Azure Service Bus** | Enterprise-grade, dead-letter queues, sessions | Additional Azure resource (~$50/mo), SDK per language, more config |
| **RabbitMQ** | Mature, flexible routing, management UI | Self-hosted in K8s (operational burden), not Azure-managed |
| **Kafka / Event Hubs** | Massive scale, replay, compaction | Extreme overkill for demo throughput, expensive, complex client config |
| **Direct HTTP webhooks** | Simplest to understand | Tight coupling, no retry/replay, no fan-out |

## Consequences

- **Positive**: Single infrastructure dependency, simple producer/consumer code, built-in consumer group acknowledgment
- **Negative**: Redis Streams don't support complex routing (topic hierarchies, filters), limited to ~1M msg/s throughput per node, no dead-letter queue (must handle failures in consumer code)
- **Operational**: Producers are .NET services using `StackExchange.Redis.StreamAddAsync`. Consumers are `ai-service` (Python) and `event-processor` (Go). Both use `XREADGROUP` with `BLOCK` for efficient polling.
