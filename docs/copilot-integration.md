# Copilot Integration Guide

[← Home](README.md)

This project uses GitHub Copilot CLI and the speckit workflow for AI-assisted development. This document explains the tooling, customization, and workflows used.

## GitHub Copilot CLI

The primary development interface is **GitHub Copilot CLI** — a terminal-based AI assistant that can explore code, make changes, run tests, and interact with Git/GitHub.

### Key Capabilities Used

| Capability | How It Was Used |
|------------|-----------------|
| **Code exploration** | `grep`, `glob`, `view` tools for navigating the 10-service codebase |
| **Code editing** | Surgical `edit` tool for precise changes across multiple files |
| **Shell execution** | Running builds (`az acr build`), deploys (`kubectl apply`), tests (`npx playwright test`) |
| **GitHub integration** | Commit, push, PR creation, issue management |
| **Sub-agent delegation** | Squad agent for parallel E2E test fixes, explore agents for codebase research |
| **Memory system** | Storing conventions (Redis port 10000, JWT HS256 fix, ACR name) for cross-session continuity |

### Copilot Instructions

The `.github/copilot-instructions.md` file provides project-specific context to Copilot:

```
.github/copilot-instructions.md
├── Active Technologies (auto-generated from speckit plans)
├── Project Structure
├── Commands
├── Code Style
└── Recent Changes
```

This file is **auto-generated** by the speckit `update-agent-context.sh` script during planning phases. Manual additions go between the `<!-- MANUAL ADDITIONS START -->` markers.

## Speckit Workflow

[Speckit](https://github.com/speckit) is a specification-driven development framework used for planning and task management.

### Workflow Phases

```
specify → plan → tasks → implement
   │         │       │         │
   ▼         ▼       ▼         ▼
 spec.md  plan.md  tasks.md  code changes
```

1. **Specify** (`/speckit.specify`) — Creates a feature specification from natural language requirements
2. **Plan** (`/speckit.plan`) — Generates implementation plan with research, data model, and contracts
3. **Tasks** (`/speckit.tasks`) — Breaks plan into dependency-ordered tasks
4. **Implement** (`/speckit.implement`) — Executes tasks in dependency order

### Project Constitution

The `.specify/memory/constitution.md` defines non-negotiable principles that gate all planning:

- **Security**: No secrets in code or K8s manifests
- **Private networking**: All Azure PaaS behind VNet/private endpoints
- **Entra ID everywhere**: DefaultAzureCredential, no connection string keys
- **Best practices**: Health checks, structured logging, graceful shutdown
- **Convention over configuration**: Derive values, minimize variables
- **Observability**: OTEL SDK, Application Insights

### Directory Structure

```
.specify/
├── memory/
│   └── constitution.md     # Project principles (gates for planning)
├── scripts/bash/
│   ├── setup-plan.sh       # Plan initialization
│   └── update-agent-context.sh  # Syncs tech context to copilot-instructions.md
├── templates/              # Plan, task, and spec templates
├── integrations/           # Integration configs
└── init-options.json       # Speckit initialization options

specs/
└── 001-backlog-implementation-plan/
    ├── spec.md             # Feature specification (8 user stories)
    ├── tasks.md            # 80 tasks across 11 phases
    ├── plan.md             # Implementation plan
    ├── research.md         # Technology research findings
    ├── data-model.md       # Entity definitions
    ├── quickstart.md       # Quick start guide
    └── contracts/          # API contracts
```

### Backlog Management

The speckit-generated `tasks.md` contains 80 tasks across 8 user stories:

| Story | Focus | Status |
|-------|-------|--------|
| US1 | Operational Readiness | ✅ Complete |
| US2 | Security Hardening | 🟡 Partial |
| US3 | Roles & RBAC | ✅ Complete |
| US4 | Observability & Testing | 🟡 In Progress |
| US5 | AI Admin Portal | ✅ Complete |
| US6 | Developer Experience | ✅ Complete |
| US7 | Infrastructure Modernization | ❌ Closed |
| US8 | Agentic Showcase | 🟡 In Progress |

## Agentic Development Patterns

### What Worked Well

1. **Specification-first planning** — Writing spec.md before code prevented scope creep and ensured all services had consistent patterns.
2. **Constitution as quality gate** — The constitution caught potential issues (e.g., hardcoded secrets, missing health checks) during planning, before code was written.
3. **Memory across sessions** — Copilot's memory system stored critical facts (Redis port 10000, JWT HS256 fix, ACR naming) that prevented repeated debugging.
4. **Sub-agent parallelism** — Squad agents fixed Playwright tests while the main session worked on infrastructure.

### What Required Human Judgment

1. **Manual one-off changes** — AI agents creating resources outside the codebase (e.g., Foundry agents via API) caused regressions. Rule: everything must be code-driven.
2. **Regression detection** — Repeated 401 errors required human investigation to understand timing issues (pod restarts, token propagation).
3. **Scope decisions** — Closing US7 (infrastructure modernization) as not worth the risk with live infra required human judgment.
4. **Security review** — `InsecureSkipVerify: true` on Redis TLS was a pragmatic choice for Azure's internal cluster IPs, but requires human sign-off.

---

[← Home](README.md)
