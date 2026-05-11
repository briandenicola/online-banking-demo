# Livingston — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** C#/.NET, Python/FastAPI, React/TypeScript, Docker Compose
- **Testing:** Minimal — App.test.tsx exists, test.sh at root, setupTests.ts present

## Learnings
- **Test coverage: ZERO meaningful tests** — Only `src/ui-app/src/App.test.tsx` exists (broken CRA boilerplate)
- **No .NET test projects** — No xUnit/NUnit/MSTest in any `.csproj`, no `*Tests` projects
- **No Python tests** — No pytest in pyproject.toml deps, no test_*.py or conftest.py files
- **No Go tests** — No `_test.go` files in event-processor
- **CI is misleading** — `.github/workflows/ci.yml` has a "test" job that only builds Contracts library, runs no tests
- **test.sh** — Manual smoke test requiring running services; tests health endpoints and basic API responses
- **Taskfile.local.yml** references `dotnet test`, `pytest`, `go test` but none have actual test code to run
- **Framework setup exists for React** — Jest + Testing Library configured in package.json and setupTests.ts
- **docker-compose.yml** supports integration testing (in-memory DBs) but no integration tests exist
- **Key paths**: test.sh (root), ci.yml (.github/workflows/), setupTests.ts (src/ui-app/src/)

## Cross-Team Findings (2026-05-05)

### From Danny (Architecture)
- **CI/CD pipeline broken** — Has "test" job but doesn't run `dotnet test`, `pytest`, `go test`
- **Terraform IaC errors** — Cloud deployment blocked; no tests to catch this

### From Basher (Backend)
- **6 critical backend bugs** — Partition key mismatch, missing money-move, missing await, route mismatch, bad lifespan, startup spam
- **These go undetected** — Zero test coverage means these critical bugs only surface in production

### From Linus (Frontend)
- **5 critical frontend bugs** — Broken test, unauthenticated fetches, client-only transfers, missing dependency, stale closure
- **Only 1 test exists** — And it's broken boilerplate

### Testing-Specific Impact
The application has ~11 critical bugs across all layers (3 infrastructure, 6 backend, 2 frontend architecture). The only defense is tests. Zero tests exist. The CI pipeline claims to test but doesn't. This is production-ready code for a banking application with no automated safety net.

### Priority for Phase 1
1. Fix CI "test" job to actually run tests
2. Wire pytest to Python service dependencies
3. Create .NET test projects (xUnit)
4. Replace broken App.test.tsx with real component tests
5. These 5 fixes unblock automated detection of all other issues

## Phase 1 Implementation (2026-05-05)

### Completed
- Created xUnit test projects for user-service (22 tests), account-service (18 tests), transfer-service (10 tests)
- Created pytest suites for ai-service (7 tests) and budget-service (8 tests)
- Fixed React tests: 14 tests across App.test.tsx, Login.test.tsx, Accounts.test.tsx
- Total: **79 passing tests** across all layers

### Technical Notes
- .NET tests use Moq for mocking, FluentAssertions for assertions
- Python tests use FastAPI TestClient (httpx-based) - no infrastructure required
- React tests required mocking react-router-dom v7 (incompatible with CRA's Jest setup)
- react-router-dom v7.14.2 has broken `main` field (points to non-existent dist/main.js)
- Created `src/__mocks__/react-router-dom.tsx` to provide Jest-compatible mock
- BCrypt.Net-Next package added by another agent may need clean build (rm bin/obj) to resolve
- user-service.Tests depends on user-service building; concurrent BCrypt changes may require coordination

## Playwright E2E Phase 1 (2026-07-14)

### Completed (E2E-101 through E2E-107)
- **E2E-101:** Scaffolded `tests/e2e/` with package.json, tsconfig.json, playwright.config.ts
- **E2E-102:** Configured baseURL=localhost, 30s timeout, retries on CI, screenshot on failure, video on retry
- **E2E-103:** Created `utils/testHelpers.ts` with waitForService, waitForAllServices, waitForPageReady, retry utilities
- **E2E-104:** Created `Taskfile.e2e.yml` with run/debug/report/install tasks, included from main Taskfile.yml
- **E2E-106:** Created POM classes: BasePage, LoginPage, DashboardPage in `pages/`
- **E2E-107:** Created `fixtures/authFixture.ts` with apiLogin helper and extended test fixture

### Architecture Decisions
- Playwright configured with chromium + firefox projects (no webkit — avoids CI flakiness)
- Auth fixture uses API-level login (POST /api/users/login) for speed, injects JWT into localStorage
- Page Objects use role-based locators (getByRole) as primary strategy for resilience
- Health check utilities use native fetch for polling (no extra deps)
- Taskfile.e2e.yml is self-contained and included via main Taskfile.yml `includes:`
- Test specs go in `tests/e2e/specs/` directory (empty until Phase 2)

### Key Paths
- `tests/e2e/playwright.config.ts` — main config
- `tests/e2e/fixtures/authFixture.ts` — auth helpers and extended test fixture
- `tests/e2e/pages/` — Page Object Models
- `tests/e2e/utils/testHelpers.ts` — health check / wait utilities
- `Taskfile.e2e.yml` — task runner integration


## Learnings

### Phase 2 Test Spec Implementation (2024)
- **Test Organization**: Created structured test suite with auth and core directories under `tests/e2e/specs/`
- **Page Object Models**: Extended POM coverage by creating RegistrationPage, AccountsPage, and TransactionsPage to complement existing LoginPage and DashboardPage
- **Auth Fixture Usage**: Core specs (dashboard, account-details, transactions) use `authenticatedPage` fixture from authFixture.ts to avoid repetitive login setup in every test
- **Resilient Selectors**: Used multiple selector strategies (role-based, data-testid, class-based) to handle different UI implementations gracefully
- **Realistic Assertions**: Tests verify visible UI elements and user-facing behavior rather than just HTTP responses
- **Test Credentials**: Tests use seeded credentials `demo@banking-demo.com` / `password123` and `testuser` / `password123`
- **JWT Token Storage**: All auth tests verify localStorage token storage pattern used by the UI app
- **Session Handling**: Tests verify token persistence, expiration handling, and cleanup on logout
- **Browser Context Testing**: Used separate browser contexts in session.spec.ts to verify cross-session behavior
- **Graceful Degradation**: Transaction and account tests handle empty states and missing pagination gracefully
- **Test Coverage Achieved**:
  - E2E-201: User registration with validation (8 tests)
  - E2E-202: Login flow with token verification (9 tests)
  - E2E-203: Session persistence and token management (7 tests)
  - E2E-204: Logout and session cleanup (9 tests)
  - E2E-205: Dashboard load and account display (12 tests)
  - E2E-206: Account details viewing (13 tests)
  - E2E-207: Transaction list display (14 tests)
- **Total**: 72 test cases across 7 spec files

## Testing Documentation & Taskfile Update (2026-07)

### Completed
- Created `docs/testing.md` — comprehensive guide covering prerequisites, quick start, all task commands, test structure, phases, config, auth fixtures, and debugging tips
- Updated `Taskfile.e2e.yml` — added `ui`, `headed`, `phase1`–`phase4` tasks (total 12 tasks now)
- All tasks verified with `task --list`; accessible via `task e2e:run`, `task e2e:ui`, etc.

### Learnings
- Taskfile.e2e.yml is included in root Taskfile.yml under `e2e:` namespace — commands use `task e2e:*` prefix
- 4 test phases: auth (4 specs), core (3 specs), advanced (6 specs), admin-ai (7 specs) = 20 spec files total
- Playwright config uses `BASE_URL` env var for override (default: http://localhost)
- App uses `auth_token` and `auth_email` localStorage keys (NOT `token`). All test references must use `auth_token`.
- Dashboard is at route `/` — no `/dashboard` route exists. DashboardPage.path must be `/`.
- Dashboard welcome heading is `<Typography variant="h4">` (renders as h4, not h1/h2).
- Logout is in a dropdown menu behind user avatar button in AppShell header. Must click avatar first, then menuitem "Sign Out".
- MUI password fields with `type="password"` appear as `textbox` role in Playwright's accessibility tree. Use `getByRole('textbox', { name: 'Password', exact: true })`.
- Registration page's "Sign In" navigation is a `<Button>` not `<a>` link. Use `getByRole('button')` not `getByRole('link')`.
- Axios 401 interceptor does `window.location.href = '/login'` on ANY 401, including login attempts. This causes a full page reload that clears React error state before tests can observe it. Invalid credential tests must verify URL stays at `/login` rather than checking for error alerts.
- Registration's email field is `type="email"` — HTML5 validation fires BEFORE React's custom `validate()`. Email format test must check `input.validity.valid` instead of MUI helperText.
- Registration client-side validation (password length, mismatch) shows errors in MUI helperText (`.MuiFormHelperText-root`), NOT in `[role="alert"]`. Only `serverError` uses `<Alert>`.
- Error message locator `[role="alert"], .MuiAlert-message` causes strict mode violations because both match the same Alert component. Use `[role="alert"]` alone.

## Smoke Test Suite (2026-05-11)

### Created
- `tests/e2e/specs/smoke/smoke.spec.ts` — 8 dedicated smoke tests covering health checks, login, dashboard, accounts, transactions, registration, admin access, and logout
- Added `smoke` project to `playwright.config.ts` using `grep: /@smoke/` — picks up all `@smoke`-tagged tests across the suite (15 total: 8 new + 7 pre-existing)
- Updated `package.json` script: `npm run test:smoke` runs `npx playwright test --project=smoke`

### How to run
- `cd tests/e2e && npm run test:smoke`
- Or: `npx playwright test --project=smoke`
- All tests run chromium-only for speed; designed to complete in < 60s

### Coverage
1. Health checks (user, account, transaction APIs)
2. Login with JWT verification
3. Dashboard loads with account data
4. Accounts page renders
5. Transactions page renders
6. Registration with unique timestamp email
7. Admin/login audit page access
8. Logout with token cleanup

## Cross-Agent Coordination (2026-05-11)

### Related Team Updates
- **Basher (Backend):** Implemented admin promote bootstrap + email lookup pattern + admin endpoints — smoke tests now cover admin tabs
- **Linus (Frontend):** Created AdminUserManagementTab.tsx and AdminLoginAuditTab.tsx — smoke tests verify new tabs are accessible
- **Turk (Infrastructure):** Fixed AI Services PE DNS zones (now 3 zones) — smoke tests verify service health through PE
