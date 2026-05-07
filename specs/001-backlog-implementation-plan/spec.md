# Feature Specification: Backlog Implementation Plan

**Branch**: `001-backlog-implementation-plan`
**Date**: 2026-05-07
**Status**: Planning

## Overview

Implement the prioritized backlog (22 items, P0–P5) for the online-banking-demo project, evolving it from a working demo into a production-grade showcase of agentic coding, secure cloud-native architecture, and workshop-style documentation — modeled after briandenicola/eShopOnAKS.

## User Stories

### US1 (P0): Operational Readiness
As a developer, I need all containers rebuilt and infrastructure applied so the current codebase runs correctly on AKS.

### US2 (P1): Security Hardening
As a platform engineer, I need Kubernetes hardened with Istio mTLS, network policies, KeyVault CSI driver, and verified Redis Entra auth so that the application meets the constitutional security principles.

### US3 (P1): User Roles & RBAC
As a product owner, I need Admin and User roles with fine-grained access control so different personas have appropriate permissions.

### US4 (P2): Observability & Testing
As a developer, I need OTEL documentation, Playwright E2E tests, and Trivy scanning so the platform is observable, tested, and secure by default.

### US5 (P3): AI Admin Portal
As an admin, I need a prompt testing UI integrated with Azure AI Foundry Evals/Red teaming SDK so I can iterate on AI service prompts with built-in evaluation.

### US6 (P4): Developer Experience
As a new contributor, I need DevContainer, workshop-style docs, architecture diagrams, and a ToC hub so I can go from clone to running in 15 minutes.

### US7 (P4): Infrastructure Modernization
As a platform engineer, I need Terraform modularized, enhanced Taskfile, and chaos engineering so infrastructure is maintainable and resilient.

### US8 (P5): Agentic Showcase
As a showcase viewer, I need Squad documentation, Copilot integration guide, and ADRs so the project demonstrates agentic development practices.

## Acceptance Criteria

- All 9 services deploy and pass health checks on AKS
- Zero secrets in K8s Secrets (all via KeyVault CSI)
- mTLS between all pods (Istio sidecar injection verified)
- E2E tests pass in CI
- Workshop docs follow eShopOnAKS pattern (concept → steps → output → challenge)
- Admin can execute prompt evaluations via Foundry SDK
- `task deploy` is idempotent and takes <10 minutes from clean state

## Non-Functional Requirements

- All constitutional principles enforced (Security, Private Networking, Entra, Best Practices, Convention, Observability)
- No public endpoints except Istio ingress gateway
- Secret rotation every 2 minutes via CSI driver
- OTEL traces propagate across all service boundaries
