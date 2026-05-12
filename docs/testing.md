# Testing Guide — Online Banking Demo

[← Azure Auth](azure-auth.md) | [Home](README.md)

## Overview

The E2E test suite uses [Playwright](https://playwright.dev/) with TypeScript. Tests are organized in 4 phases covering authentication, core banking, transfers/budgets, and admin/AI features.

**Location:** `tests/e2e/`

The Account Opening Service also has its own unit/integration test suite and an E2E smoke test.

### Account Opening Service Tests

**Unit/integration tests** are located at `src/account-opening-service/tests/` and cover:

- `test_api.py` — API endpoint tests (submit application, get status, get events)
- `test_document_extraction.py` — CUS document extraction stage
- `test_identity_verification.py` — Foundry identity verification agent
- `test_compliance_check.py` — Foundry KYC/AML compliance agent
- `test_provisioning.py` — Account provisioning agent
- `test_consumer.py` — Redis Stream consumer logic
- `test_state_machine.py` — Application state transitions
- `test_events.py` — Event publishing/handling
- `test_models.py` — Data model validation
- `test_worker.py` — Worker startup and wiring

```bash
# Run account opening service tests
cd src/account-opening-service
pip install -e ".[dev]"
pytest tests/
```

**E2E smoke test** at `tests/e2e/specs/core/account-opening.spec.ts` tests the full pipeline: submit application → document extraction → identity verification → compliance check → account provisioning.

## Prerequisites

1. **Docker Compose** — The application must be running locally:
   ```bash
   docker compose up -d
   ```
2. **Node.js** ≥ 18
3. **Playwright browsers** — Installed via the install task (see below)

## Quick Start

```bash
# Install dependencies and browsers
task e2e:install

# Start the app (if not already running)
task local:up    # or: docker compose up -d

# Run all tests
task e2e:run

# Run in UI mode (interactive)
task e2e:ui

# Run headed (see browser)
task e2e:headed
```

## Taskfile Commands

| Command | Description |
|---------|-------------|
| `task e2e:install` | Install npm deps + Playwright browsers |
| `task e2e:run` | Run all E2E tests (headless) |
| `task e2e:ui` | Open Playwright UI mode (interactive test runner) |
| `task e2e:headed` | Run tests with visible browser |
| `task e2e:debug` | Run with Playwright Inspector (step-through) |
| `task e2e:phase1` | Run Phase 1 — Auth specs only |
| `task e2e:phase2` | Run Phase 2 — Core banking specs |
| `task e2e:phase3` | Run Phase 3 — Transfers & budgets |
| `task e2e:phase4` | Run Phase 4 — Admin, chatbot, concurrency |
| `task e2e:chromium` | Run in Chromium only |
| `task e2e:firefox` | Run in Firefox only |
| `task e2e:report` | Open last HTML test report |

## Test Structure

```
tests/e2e/
├── playwright.config.ts        # Config (baseURL, timeouts, projects)
├── package.json                # Dependencies
├── tsconfig.json               # TypeScript config
├── fixtures/
│   └── authFixture.ts          # API-level auth + extended test fixture
├── pages/                      # Page Object Models
│   ├── BasePage.ts
│   ├── LoginPage.ts
│   ├── RegistrationPage.ts
│   ├── DashboardPage.ts
│   ├── AccountsPage.ts
│   ├── TransactionsPage.ts
│   ├── TransfersPage.ts
│   ├── BudgetPage.ts
│   ├── AdminPage.ts
│   └── ChatbotPage.ts
├── utils/
│   └── testHelpers.ts          # waitForService, retry utilities
└── specs/
    ├── auth/                   # Phase 1 — Authentication
    │   ├── registration.spec.ts
    │   ├── login.spec.ts
    │   ├── session.spec.ts
    │   └── logout.spec.ts
    ├── core/                   # Phase 2 — Core Banking
    │   ├── dashboard.spec.ts
    │   ├── account-details.spec.ts
    │   └── transactions.spec.ts
    ├── advanced/               # Phase 3 — Transfers & Budgets
    │   ├── transfers-happy-path.spec.ts
    │   ├── transfers-validation.spec.ts
    │   ├── transfers-concurrent.spec.ts
    │   ├── budget-view.spec.ts
    │   ├── budget-editing.spec.ts
    │   └── anomaly-detection.spec.ts
    └── admin-ai/               # Phase 4 — Admin & AI
        ├── admin-access.spec.ts
        ├── admin-user-management.spec.ts
        ├── admin-user-actions.spec.ts
        ├── chatbot-interaction.spec.ts
        ├── chatbot-context.spec.ts
        ├── chatbot-fallback.spec.ts
        └── multi-user-concurrency.spec.ts
```

## Phases

| Phase | Directory | Coverage | Tests |
|-------|-----------|----------|-------|
| 1 | `specs/auth/` | Registration, login, sessions, logout | ~33 |
| 2 | `specs/core/` | Dashboard, accounts, transactions | ~39 |
| 3 | `specs/advanced/` | Transfers, budgets, anomaly detection | ~61 |
| 4 | `specs/admin-ai/` | Admin panel, chatbot, concurrency | ~62 |

## Running Individual Specs

```bash
cd tests/e2e

# Single file
npx playwright test specs/auth/login.spec.ts

# By grep pattern
npx playwright test -g "successful login"

# Single project (browser)
npx playwright test --project=chromium specs/core/
```

## Configuration

Key settings in `playwright.config.ts`:

- **Base URL:** `http://localhost` (override with `BASE_URL` env var)
- **Browsers:** Chromium + Firefox
- **Timeouts:** 30s test, 10s expect, 15s action/navigation
- **CI mode:** Single worker, 1 retry, `forbidOnly` enforced
- **Artifacts:** Screenshots on failure, video on first retry, trace on first retry

## Authentication

Tests use an API-level auth fixture (`fixtures/authFixture.ts`) that:
1. POSTs to `/api/users/login` with test credentials
2. Injects the JWT into `localStorage`
3. Provides an `authenticatedPage` fixture for specs that need a logged-in user

Test credentials (seeded in dev data):
- `demo@banking-demo.com` / `password123`
- `testuser` / `password123`

## Debugging Tips

- **UI Mode** (`task e2e:ui`): Best for exploring failures interactively
- **Headed** (`task e2e:headed`): Watch tests execute in real browser
- **Debug** (`task e2e:debug`): Step through with Playwright Inspector
- **Trace viewer**: After a failed CI run, download traces from `test-results/` and open with `npx playwright show-trace <file>`
- **Screenshots**: Saved to `test-results/` on failure

## CI Integration

Tests run in GitHub Actions via `.github/workflows/ci.yml`. In CI:
- Single worker (sequential execution)
- 1 retry on failure
- HTML report + trace artifacts uploaded

---

[← Azure Auth](azure-auth.md) | [Home](README.md)
