# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for the Online Banking Demo. ADRs capture significant technical decisions made during development, along with their context and consequences.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [001](001-istio-over-linkerd.md) | Istio over Linkerd for service mesh | Accepted | 2026-05 |
| [002](002-keyvault-csi-over-external-secrets.md) | KeyVault CSI over External Secrets Operator | Accepted | 2026-05 |
| [003](003-jwt-claim-roles.md) | JWT claim-based roles over external RBAC | Accepted | 2026-05 |
| [004](004-redis-streams-event-bus.md) | Redis Streams as event bus over dedicated message brokers | Accepted | 2026-05 |
| [005](005-foundry-agents-over-direct-openai.md) | Azure AI Foundry agents over direct OpenAI calls | Accepted | 2026-05 |
| [006](006-llm-as-judge-evaluation.md) | LLM-as-judge for prompt evaluations over Foundry's hosted evals (raisvc) | Accepted | 2026-05 |

## ADR Format

Each ADR follows this structure:

```markdown
# ADR-NNN: Title

**Status**: Proposed | Accepted | Deprecated | Superseded
**Date**: YYYY-MM
**Author**: Name

## Context
What is the issue that we're seeing that motivates this decision?

## Decision
What is the change that we're proposing and/or doing?

## Alternatives Considered
What other options were evaluated?

## Consequences
What becomes easier or more difficult because of this change?
```

---

[← Home](../README.md)
