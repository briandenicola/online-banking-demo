# Squad Guide — AI Team Development

[← Home](README.md)

This project was developed using **Squad**, an AI team framework that assigns specialized agent roles to collaborate on software engineering tasks. This document captures how Squad was configured and used.

## What is Squad?

Squad creates a team of AI agents, each with a defined role and charter, that collaborate through structured handoffs and decision records. Think of it as a virtual engineering team where each member has a specialty.

## Team Configuration

The team is defined in `.squad/team.md` and consists of:

| Agent | Role | Specialty |
|-------|------|-----------|
| **Danny** | Lead / Architect | Architecture decisions, design reviews, cross-cutting concerns |
| **Basher** | Backend Developer | .NET services, Go event-processor, Redis, Cosmos DB, infrastructure |
| **Linus** | Frontend Developer | React UI, MUI components, TypeScript, browser-side auth |
| **Livingston** | Tester / QA | Playwright E2E tests, test strategy, quality gates |
| **Turk** | Backend Developer | Python services (AI, chatbot, budget), FastAPI, Azure AI Foundry |
| **Scribe** | Session Logger | Decision records, session summaries, documentation |
| **Ralph** | Work Monitor | Progress tracking, dependency resolution |

## How Squad Was Used

### Architecture Decisions

Danny (Lead/Architect) produced the `.squad/decisions/decisions.md` file containing formal decision records for:

- OTEL Collector deployment strategy
- Redis Entra ID dual-mode authentication pattern
- Cosmos DB container partitioning
- Service-to-service JWT forwarding
- Balance update side-effects ownership

### Development Workflow

1. **Brian describes the work** — natural language requirements
2. **Squad Coordinator** routes work to the appropriate agent(s)
3. **Agent produces work** — code changes, tests, configurations
4. **Decision records captured** — significant choices documented in `.squad/decisions/`
5. **Review gates** — changes reviewed before merge

### Key Contributions by Agent

**Basher** (Backend):
- Redis cluster client fixes for Azure Managed Redis (both .NET and Go)
- Event-processor `XREADGROUP` consumer implementation
- Cosmos DB Entra RBAC authentication across all .NET services
- Transfer service JWT forwarding for service-to-service auth

**Turk** (Backend/Python):
- AI service risk scoring with Foundry agents
- Chatbot service with Agent Framework and account/transaction tools
- Budget service spending analysis
- Redis Streams consumer for AI processing

**Linus** (Frontend):
- React UI with MUI v9 components
- Admin panel (user management, prompt evaluation)
- Auth context with JWT token management
- Dashboard, accounts, transactions, transfers pages

**Livingston** (QA):
- Playwright E2E test suite (195+ specs across 4 phases)
- Page Object Model architecture
- Auth fixture for API-level login
- Test helpers and retry utilities

## Directory Structure

```
.squad/
├── agents/                  # Individual agent charters
│   ├── basher/charter.md
│   ├── danny/charter.md
│   ├── linus/charter.md
│   ├── livingston/charter.md
│   ├── ralph/
│   ├── scribe/charter.md
│   └── turk/charter.md
├── decisions/               # Architecture Decision Records
│   ├── decisions.md         # All formal decisions
│   └── inbox/               # Pending decisions
├── config.json              # Squad configuration
├── team.md                  # Team roster and context
├── routing.md               # Work routing rules
├── ceremonies.md            # Team ceremonies (standups, reviews)
└── templates/               # Decision and handoff templates
```

## Lessons Learned

1. **Specialized roles reduce context switching** — Basher handles .NET/Go/infra, Turk handles Python/AI. Each agent maintains deep context in their domain.
2. **Decision records are valuable** — The `.squad/decisions/decisions.md` file captures why things were built a certain way, which is invaluable when debugging regressions.
3. **Review gates catch issues** — Agent work products go through review before integration, catching issues like the "risk-analyzer" vs "risk-assessor" naming mismatch.
4. **Human oversight is essential** — Brian's rule of "no one-off manual changes outside the codebase" emerged from Squad agents making ad-hoc fixes that weren't committed.

---

[← Home](README.md)
