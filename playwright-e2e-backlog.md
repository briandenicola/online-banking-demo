# Playwright E2E Testing Backlog — Online Banking Demo

## Executive Summary
Comprehensive end-to-end testing strategy spanning Playwright setup, core banking workflows, admin features, AI integrations, and Playwright MCP tooling for squad development workflows. Organized in 4 phases with 24 backlog items.

---

## Phase 1: Playwright Foundation & Infrastructure (P0 — Critical)

| ID | Title | Description | Labels | Priority | Dependencies | Est. Effort |
|----|-------|-------------|--------|----------|--------------|-------------|
| E2E-101 | Playwright project scaffolding | Initialize Playwright project with TypeScript config, tsconfig, ESLint. Set up test directory structure (`tests/e2e`). Configure browser targets (chromium, firefox, webkit). | `testing`, `e2e`, `infrastructure` | P0 | — | 3 pts |
| E2E-102 | Playwright.config base setup | Configure baseURL (http://localhost), timeouts (30s), retries, screenshot/video capture on failure. Add `test.slow()` markers for long-running tests. | `testing`, `e2e`, `infrastructure` | P0 | E2E-101 | 2 pts |
| E2E-103 | Docker Compose health checks & waiter | Add `wait-for-it.sh` or Node polling to verify all services healthy before tests run. Implement `utils/testHelpers.ts` with retry/polling utilities. | `testing`, `e2e`, `infrastructure` | P0 | E2E-101 | 3 pts |
| E2E-104 | Taskfile integration — `test:e2e` target | Add `task e2e:run` (runs docker-compose up, waits for health, executes playwright), `task e2e:debug` (headed mode), `task e2e:report` (HTML report viewer). | `testing`, `e2e`, `infrastructure` | P0 | E2E-101, E2E-103 | 2 pts |
| E2E-105 | CI/CD GitHub Actions workflow | Create `.github/workflows/e2e.yml`: runs on PR merge, starts docker-compose, runs Playwright headless, uploads report artifact, posts summary to PR. | `testing`, `e2e`, `ci-cd` | P0 | E2E-102, E2E-103, E2E-104 | 4 pts |
| E2E-106 | Page Object Models (POM) architecture | Establish POM pattern with base page class, locator centralization, helper methods. Create: `pages/BasePage.ts`, `pages/LoginPage.ts`, `pages/DashboardPage.ts`. Document conventions. | `testing`, `e2e`, `infrastructure` | P0 | E2E-101 | 2 pts |
| E2E-107 | Test fixtures & auth helpers | Implement `fixtures/authFixture.ts` to register/login users, extract JWT tokens. Enable test parallelization with isolated fixtures. | `testing`, `e2e`, `infrastructure` | P0 | E2E-102, E2E-106 | 3 pts |

---

## Phase 2: Authentication & Core Flows (P0 — Blocking)

| ID | Title | Description | Labels | Priority | Dependencies | Est. Effort |
|----|-------|-------------|--------|----------|--------------|-------------|
| E2E-201 | User registration flow test | Test: email validation, password requirements, terms checkbox, submit, success redirect to login. Verify: user created in backend, can login. | `testing`, `e2e`, `auth` | P0 | E2E-107 | 3 pts |
| E2E-202 | User login flow test | Test: valid credentials → JWT token redirect to dashboard, invalid credentials → error message. Verify: token stored, subsequent requests use it. | `testing`, `e2e`, `auth` | P0 | E2E-107, E2E-201 | 3 pts |
| E2E-203 | Session persistence & token refresh | Test: login, close browser, reopen → session persists (token in localStorage). Test: expired token → auto-refresh or re-login prompt. | `testing`, `e2e`, `auth` | P0 | E2E-202 | 2 pts |
| E2E-204 | Logout & session cleanup | Test: click logout, verify token removed, redirect to login, cannot access protected pages. | `testing`, `e2e`, `auth` | P0 | E2E-202 | 2 pts |
| E2E-205 | Dashboard load & account display | Test: login → dashboard loads, all accounts visible with correct balances, account cards render properly. | `testing`, `e2e`, `core` | P0 | E2E-202 | 2 pts |
| E2E-206 | View account details | Test: click account card → detail page loads, transactions listed, balance breakdown shown. | `testing`, `e2e`, `core` | P1 | E2E-205 | 2 pts |
| E2E-207 | Transaction list pagination | Test: transactions page loads, pagination works (next/prev/jump), sorting by date/amount, filtering by type. | `testing`, `e2e`, `core` | P1 | E2E-206 | 3 pts |

---

## Phase 3: Money Movement & Advanced Features (P1 — Core Functionality)

| ID | Title | Description | Labels | Priority | Dependencies | Est. Effort |
|----|-------|-------------|--------|----------|--------------|-------------|
| E2E-301 | Transfer between accounts (happy path) | Test: user transfers $100 from checking to savings → both accounts updated instantly, new transaction appears in history. | `testing`, `e2e`, `transfers` | P1 | E2E-207 | 4 pts |
| E2E-302 | Transfer validation & error handling | Test: insufficient balance → error msg, invalid amount → validation error, same account → prevent self-transfer. | `testing`, `e2e`, `transfers` | P1 | E2E-301 | 2 pts |
| E2E-303 | Concurrent transfers — race condition test | Test: user initiates two simultaneous transfers from same account → only one succeeds, proper error on second. | `testing`, `e2e`, `transfers` | P2 | E2E-302 | 3 pts |
| E2E-304 | Budget/spending view | Test: budget page loads, spending breakdown by category shown, trends chart renders, budget thresholds visualized. | `testing`, `e2e`, `budgets` | P1 | E2E-205 | 3 pts |
| E2E-305 | Budget creation & editing | Test: create new budget (name, limit, category), edit existing budget, delete budget. Verify backend persistence. | `testing`, `e2e`, `budgets` | P1 | E2E-304 | 3 pts |
| E2E-306 | Anomaly detection — suspicious activity alert | Test: large transaction triggers anomaly flag, banner appears on dashboard, user can review & dismiss. Mock or test with Azure if available. | `testing`, `e2e`, `anomaly` | P1 | E2E-301 | 2 pts |

---

## Phase 4: Admin & AI Features (P1-P2 — Advanced)

| ID | Title | Description | Labels | Priority | Dependencies | Est. Effort |
|----|-------|-------------|--------|----------|--------------|-------------|
| E2E-401 | Admin dashboard access & permission check | Test: non-admin cannot see admin link, admin user logs in → admin dashboard accessible. Verify: stats cards load (user count, total transactions, etc.). | `testing`, `e2e`, `admin` | P1 | E2E-202 | 2 pts |
| E2E-402 | Admin user management — list & filter | Test: admin page shows user list, can filter by status (active/suspended), sort by registration date. Pagination works. | `testing`, `e2e`, `admin` | P1 | E2E-401 | 2 pts |
| E2E-403 | Admin user actions — suspend/unsuspend | Test: click suspend on user → user account flagged, user cannot login, re-enable reverses it. | `testing`, `e2e`, `admin` | P1 | E2E-402 | 2 pts |
| E2E-404 | Chatbot interaction — message flow | Test: user types question → chatbot responds, conversation history shown, multiple turns work. Use mock if Azure OpenAI unavailable. | `testing`, `e2e`, `chatbot` | P2 | E2E-205 | 3 pts |
| E2E-405 | Chatbot memory & context | Test: chatbot recalls previous context across multiple messages (e.g., "I have $5k, what should I invest?" → follow-up "Is that enough?"). | `testing`, `e2e`, `chatbot` | P2 | E2E-404 | 2 pts |
| E2E-406 | Chatbot fallback — Azure unavailable | Test: when Azure OpenAI down, chatbot displays graceful error/mock response instead of blank/crash. | `testing`, `e2e`, `chatbot` | P2 | E2E-404 | 2 pts |
| E2E-407 | Multi-user concurrency test | Test: 3+ users login simultaneously, each performs independent actions (transfers, budget edits), no data leakage or race conditions. | `testing`, `e2e`, `core` | P2 | E2E-301, E2E-304 | 4 pts |

---

## Phase 5: Playwright MCP Integration for Squad (P0 — Tooling)

| ID | Title | Description | Labels | Priority | Dependencies | Est. Effort |
|----|-------|-------------|--------|----------|--------------|-------------|
| E2E-501 | Playwright MCP server implementation | Implement MCP server (Node.js or Python) that exposes Playwright actions: `navigate(url)`, `click(selector)`, `fill(selector, text)`, `screenshot()`, `getPageState()`, `extractText(selector)`. Store session context (browser/page instances). | `testing`, `mcp`, `infrastructure` | P0 | — | 8 pts |
| E2E-502 | MCP configuration & integration with squad tooling | Add MCP server config to `.squad/mcp-config.json`. Register MCP tool in squad's available skills. Document how team members invoke MCP during development (e.g., `/playwright navigate http://localhost/dashboard`). | `testing`, `mcp`, `infrastructure` | P0 | E2E-501 | 3 pts |
| E2E-503 | MCP — Page navigation & interaction tools | MCP action set: `navigate(url, waitSelector?)`, `click(selector)`, `fill(selector, text)`, `hover(selector)`, `press(key)`, `screenshot(filename)`. Enable squad to drive app without browser. | `testing`, `mcp`, `tooling` | P0 | E2E-501 | 4 pts |
| E2E-504 | MCP — State inspection & assertion tools | MCP action set: `getPageState()` (returns DOM snapshot), `extractText(selector)`, `countElements(selector)`, `isVisible(selector)`, `getAttribute(selector, attr)`. Squad can verify UI state during debugging. | `testing`, `mcp`, `tooling` | P0 | E2E-501 | 3 pts |
| E2E-505 | MCP — Session management for squad | MCP actions: `launchBrowser()`, `newPage()`, `closePage()`, `getBrowserSessions()`, `setAuthToken(token)` (for authenticated workflows). Allow squad to parallelize independent test scenarios. | `testing`, `mcp`, `tooling` | P0 | E2E-502 | 3 pts |
| E2E-506 | Squad documentation — Using Playwright MCP | Write guide: `docs/playwright-mcp-guide.md` — what is MCP, how to use it, examples (e.g., "test a new checkout flow without writing Playwright code"), troubleshooting. | `testing`, `mcp`, `documentation` | P1 | E2E-502 | 2 pts |
| E2E-507 | Playwright MCP testing & validation | Test MCP server with squad usage scenarios: navigate app, take screenshot, extract data, assert state. Verify performance (< 1s round-trip), error handling. | `testing`, `mcp`, `infrastructure` | P1 | E2E-503, E2E-504, E2E-505 | 4 pts |

---

## Cross-Cutting Concerns & Testing Patterns

### Data & State Management
- **Test isolation:** Each test cleans up data (users/accounts/transactions) via fixtures, no test pollution
- **Seed data:** Use `scripts/seed-data.sh` in setup to create predictable baseline (3 users, 6 accounts, 20 transactions)
- **Mock Azure services:** Chatbot/anomaly detection use mocks when Azure unavailable

### Performance & Reliability
- **Retry logic:** Transient failures (container startup delays) retried up to 3 times
- **Timeouts:** UI waits capped at 30s, API calls at 10s
- **Screenshot/video capture:** On failure, uploaded to GitHub Actions artifact for post-mortem

### Security & Privacy
- **No hardcoded credentials:** Auth fixtures use dynamic user creation or GitHub Secrets for CI
- **JWT token handling:** Stored in fixture, injected into requests, verified in assertions
- **Admin tests:** Use separate admin-role user, never elevate regular user permissions in tests

---

## Success Criteria & Acceptance

✅ **Phase 1 (Weeks 1-2):** All infrastructure & Taskfile integration complete; tests run locally & in CI  
✅ **Phase 2 (Weeks 2-3):** Auth flows 100% covered; user can register→login→logout without flakiness  
✅ **Phase 3 (Weeks 3-4):** Money movement tested end-to-end; transfers verified with backend state  
✅ **Phase 4 (Weeks 4-5):** Admin & chatbot flows covered; graceful degradation when Azure unavailable  
✅ **Phase 5 (Weeks 5-6):** MCP server operational; squad can navigate app & inspect state via MCP commands  

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Docker Compose startup delays | Health checks + polling; 60s timeout in tests |
| Flaky timing (elements appear after animation) | Use `waitForLoadState('networkidle')`, explicit waits |
| Azure OpenAI downtime breaks chatbot tests | Mock chatbot service in test environment |
| MCP server performance | Cache browser/page instances; monitor round-trip latency |
| Concurrent test interference | Use test.describe.parallel() with isolated fixtures per test |

---

## Effort & Timeline Estimate

- **Phase 1:** 19 pts (~2 weeks)
- **Phase 2:** 12 pts (~1.5 weeks)
- **Phase 3:** 17 pts (~2 weeks)
- **Phase 4:** 16 pts (~2 weeks)
- **Phase 5:** 25 pts (~3 weeks)
- **Total:** ~10.5 weeks (includes review/refinement cycles)

---

## Tech Stack & Dependencies

- **Playwright:** ^1.40.0 (TypeScript, Chromium/Firefox/WebKit)
- **MCP:** Node.js server exposing Playwright APIs
- **Docker Compose:** Existing, no changes needed
- **GitHub Actions:** Existing, add new E2E workflow
- **Taskfile:** Extend with E2E targets

---

## Related Team Decisions

From `.squad/decisions.md`:
- **Redis Streams event architecture:** E2E tests verify transaction flow end-to-end, including event propagation
- **Gateway JWT validation:** E2E tests confirm token validation + CORS headers work
- **Kubernetes deployment readiness:** E2E tests run against docker-compose; cloud/K8s deployment validated separately via smoke tests

