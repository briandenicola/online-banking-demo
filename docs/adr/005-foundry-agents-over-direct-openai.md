# ADR-005: Azure AI Foundry Agents over Direct OpenAI Calls

**Status**: Accepted  
**Date**: 2026-05  
**Author**: Brian De Nicola

## Context

The application uses AI for three capabilities: risk scoring (fraud detection), transaction categorization, and conversational financial advice. These could be implemented as direct OpenAI API calls with prompt templates, or as Azure AI Foundry agents with persistent identity and tool integration.

## Decision

Use **Azure AI Foundry agents** via the `azure-ai-projects` SDK and `agent-framework-foundry` package, with agents registered at service startup via `create_version()`.

### Reasons

1. **Agent identity** — Named agents (`risk-assessor`, `transaction-categorizer`) are registered in Azure AI Foundry with versioned definitions. This provides auditability, portal visibility, and version management.
2. **Tool binding** — The chatbot agent uses Foundry's tool framework to call account and transaction APIs with real data, enabling grounded responses rather than hallucinated financial advice.
3. **Startup registration** — Agents are created programmatically in the `ai-service` lifespan handler using `AIProjectClient.agents.create_version()` with `PromptAgentDefinition`. No manual portal setup required — the code is the source of truth.
4. **Model flexibility** — Agent definitions reference a deployment name (`gpt-5.4-mini`), decoupling the application from specific model versions. Model upgrades happen at the deployment level.

## Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **Direct OpenAI API** | Simpler code, no agent framework | No agent identity, prompt templates scattered across code, no tool framework, no portal visibility |
| **Semantic Kernel** | Rich .NET integration, plugin ecosystem | Python services would need a different framework, over-abstraction for 2-3 agents |
| **LangChain / LangGraph** | Popular, lots of examples | Heavy dependency, opinionated abstractions, version churn |
| **FoundryAgent in-memory only** | Simplest setup | Agents invisible in portal, no versioning, no auditability |

## Consequences

- **Positive**: Agents visible in Azure AI Foundry portal, versioned definitions, tool-augmented responses, code-driven registration (no manual setup)
- **Negative**: Dependency on Azure AI Foundry SDK (prerelease), `create_version()` API may change, requires Foundry project + model deployment in Azure
- **Operational**: Agent definitions in `src/ai-service/app/main.py` lifespan handler. Chatbot agent in `src/chatbot-service/app/main.py`. All use `DefaultAzureCredential` via workload identity.
