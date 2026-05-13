# Linus — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** React/TypeScript, MUI, Create React App
- **App:** ui-app — the frontend banking interface

## Core Context

**Core Frontend Patterns:**
- Test convention: Colocated tests. `Component.tsx` + `Component.test.tsx` in same directory. No `__tests__/` directories (P2 Wave 1).
- Error handling: Central `logger` module (`src/utils/logger.ts`). All error logging goes through `logger.error()` — not direct `console.error`. No-ops in test; swallowed in prod pending telemetry.
- Type guards: Use `unknown` + inline casts instead of `any`. Pattern: `(err as { response?: { data?: { message?: string } } })?.response?.data?.message`.
- API client: Canonical names per operation (createApplication, getApplication, listApplications, etc.). Single name per endpoint, no aliases.
- Admin checks: Guarded with `isAdmin` from AuthContext before calling /admin/* endpoints. Non-admin users see partial UI (no risk scores/AI explanations).

**Current Tech Stack:**
- CRA + React 19 + MUI 9 + react-router-dom 7, TypeScript strict mode
- Nginx reverse proxy: `/api/` → `http://gateway:80/`
- AuthContext: Global auth state + accounts + transfers (god object — P3 refactoring)

**Critical Bugs (Pre-Wave 1):**
- Transfer API client had wrong shape (wrapped formData, FastAPI expects flat)
- Duplicate test files: 7 pairs, __tests__/ vs. colocated versions out of sync
- Any types: 4 instances without type guards
- Admin endpoint noise: 403s on every load for non-admin users

## Learnings

### 2025-07-18 — Frontend Code Quality Audit

**Architecture:**
- App uses CRA + React 19 + MUI 9 + react-router-dom 7 + TypeScript (strict mode)
- Flat file structure: `src/pages/` (6 pages), `src/context/` (1 context)
- No shared components directory, no API client layer
- Nginx reverse proxy at `/api/` → `http://gateway:80/`

**Key Files:**
- `src/App.tsx` — Router, theme, protected route logic
- `src/context/AuthContext.tsx` — God object: auth + accounts + transfers
- `src/pages/Transactions.tsx` — Largest component (~385 lines), fetches from `/api/transactions`
- `src/pages/Chat.tsx` — AI chat via `/api/chat`

**Critical Bugs Found:**
1. `App.test.tsx` — broken test (looks for "learn react" that doesn't exist)
2. `AuthContext.tsx:43` — fetches accounts without auth token on mount
3. `AuthContext.tsx:61` — transfer() is client-only, never persists to backend
4. `Transactions.tsx:99-101` — useEffect missing `token` dependency
5. `Chat.tsx:28` — stale closure on messages state update

**Patterns:**
- API calls use raw `fetch()` despite `axios` being in package.json
- Auth token passed inconsistently (some calls include it, others don't)
- Add Account dialog duplicated in Accounts.tsx and Transactions.tsx
- `App.css` and `logo.svg` are dead CRA boilerplate

## Cross-Team Findings (2026-05-05)

### From Danny (Architecture)
- **No CORS configuration** — Nginx gateway has zero auth/CORS config, blocking frontend cross-origin API calls
- **API Gateway lacks auth middleware** — All requests pass through unverified; frontend auth token handling won't protect anything

### From Basher (Backend)
- **Transfer backend missing** — These 5 critical frontend bugs about transfer API are moot if backend transfer-service never moves money (core logic missing)
- **Budget-Chatbot route mismatch** — Frontend chat integration can't work because budget service routes don't match chatbot expectations
- **No input validation** — Frontend sends data that backend doesn't validate; garbage gets through

### From Livingston (Test/QA)
- **Broken test means no CI safety** — App.test.tsx failure goes unnoticed
- **Zero component/integration tests** — Can't catch the 5 critical bugs Linus found

### Frontend-Specific Impact
The 5 critical bugs (broken test, unauthenticated account fetch, client-only transfers, missing dependency, stale closure) are compounded by backend issues. Transfer API doesn't exist at all. Auth token handling is inconsistent because frontend tries to work around missing backend auth. God object AuthContext can't be tested because no test framework runs.

## 2026-05 — Parallel Backlog Batch (May 6)

### User Registration UI

**Scope:** Added RegisterPage.tsx and /register route to enable user self-registration.

**Implementation:**
- RegisterPage.tsx: Email + password + confirm password form with validation
- Form validation: Email format, password length, password match
- Submit: POST to /api/users/register (implemented by Basher)
- Success flow: Navigate to LoginPage with "Account created" toast
- Error handling: Display validation errors from backend (400 responses)

**Integration:** LoginPage.tsx now includes "Don't have an account? Register here" link. Users flow from login → register → create account → login again.

**Outcome:** User signup flow complete end-to-end. Supports new user onboarding without manual admin provisioning.

### Admin Dashboard UI

**Scope:** Added AdminPage.tsx with stats cards, flagged transactions table, and review actions.

**Implementation:**
- AdminPage.tsx: Dashboard layout with MUI Grid
- Stats cards: User count, total accounts, total transactions (fetches from /api/admin/stats)
- Flagged transactions DataGrid: Columns for date, user, amount, anomaly reason, action buttons
- Review actions: Approve/Reject buttons with POST to /api/admin/review
- Protected route: /admin only accessible with admin token; redirects to LoginPage if unauthorized
- Loading states: Spinners during data fetch and action submission
- Toast notifications: Feedback on successful/failed review actions

**API Integration:**
- GET /api/admin/stats: Fetches and displays KPIs on mount
- GET /api/admin/flagged-transactions: Populates table with pagination
- POST /api/admin/review: Submits review action (approve/reject)

**UX Flow:**
1. Admin login → /admin route (if authorized)
2. Dashboard loads stats cards (user count, accounts, transactions)
3. Flagged transactions table displays anomalies
4. Admin clicks Approve/Reject button
5. Action submitted to backend; table refreshes
6. Toast confirms action result

**Outcome:** Admin dashboard fully functional. Admins can now review and act on flagged transactions without backend access.

**Cross-Team Impact:**
- Basher (Backend): Implemented corresponding /api/admin/* endpoints and Redis flagged transaction storage
- Danny (Infrastructure): nginx routing for /api/admin/* verified
- All branches merged to main; AdminPage production-ready

### Premium Banking UI Theme (Backlog)

**Status:** Assigned to Linus (backlog priority, next sprint)

**Scope:** Redesign UI with professional banking aesthetic (JPMC/BofA style).

**Planned Work:**
- Color palette: Navy/dark blue primary, white/gray surfaces, gold/green accents
- Typography scale: Hierarchy across headings, body, labels
- Navigation redesign: Header with account summary hero section
- Dashboard layout: Card-based grid with KPIs
- Transaction table: Status badges, icons, professional styling
- Transfer flow: Polished multi-step form

**Dependencies:** Complete; no backend dependencies. MUI theme update only.


## Learnings

### UI Theme Redesign (squad/ui-theme)
- MUI v9 removed `fontWeight`, `display`, and similar shorthand props from Typography — must use `sx` prop instead
- MUI v9 renamed `primaryTypographyProps`/`secondaryTypographyProps` on ListItemText to `slotProps.primary`/`slotProps.secondary`
- When using mock routers in tests (that render all Route children), assertions should use `getAllBy*` instead of `getBy*` to handle multiple rendered pages
- Professional banking aesthetic relies on: deep navy primary, gold accent, system font stack, subtle shadows (elevation 1-2), 12px border-radius on cards, and clear visual hierarchy through font-weight rather than color

### 2025-07-22 — Transactions Endpoint Fix
- Changed `GET /transactions` → `GET /transactions/my` in Transactions.tsx (line 78)
- The `/transactions/my` endpoint returns the authenticated user's transactions
- The POST to `/transactions` for creating new transactions was left unchanged (correct endpoint)
- Admin pages use separate endpoints (e.g., `/transactions/flagged`) — not touched

### 2026-05-06 — Nginx CrashLoopBackOff Fix
- **Root cause:** Pod was in CrashLoopBackOff because `pid` directive was duplicated — once in the base nginx:alpine image's `/etc/nginx/nginx.conf` and again via Dockerfile CMD `-g "pid /tmp/nginx.pid;"`. Also, `user` directive warned because container runs as non-root.
- **Fix:** Promoted `nginx.conf` from a server-block fragment (copied to `conf.d/default.conf`) to a full main config (copied to `/etc/nginx/nginx.conf`), replacing the base image's default entirely.
- Removed `user` directive (not needed when running as non-root via `USER nginx`)
- Set `pid /tmp/nginx.pid;` in the config file itself, removed it from CMD
- Added `/tmp` temp paths (`client_body_temp_path`, `proxy_temp_path`, etc.) for read-only root filesystem compatibility in Kubernetes
- Pre-created temp directories in Dockerfile RUN step with proper nginx ownership
- **Lesson:** When customizing nginx in non-root containers, always replace the full main config to avoid directive conflicts with the base image defaults

### 2026-05-07 — Nginx Gateway Proxy Removal
- Removed `location /api/` and `location @fallback_api` blocks from `src/ui-app/nginx.conf`
- The gateway service was deleted when the project moved to Istio; the stale `proxy_pass http://gateway:80` caused nginx DNS resolution failures and CrashLoopBackOff in K8s
- Istio VirtualService (`cluster-config/istio/gateway/default-ingress.yaml`) now handles all `/api/*` routing at the mesh level
- nginx.conf now only serves static files with SPA fallback — no proxy responsibilities

### 2026-05-07 — addAccount API Integration Fix
- `addAccount` in `AccountContext.tsx` was local-only (never called backend); now calls `POST /accounts` via apiClient
- Backend `CreateAccountRequest` expects `{ accountType, initialBalance, currency? }` — form fields map: `type` → `accountType`, `balance` → `initialBalance`
- Server response `{ id, accountNumber, accountType, balance, currency }` is mapped to local `Account` using same logic as `fetchAccounts`
- Removed `nextAccountId` state — IDs are server-generated
- Both callers updated: `Accounts.tsx` (with error Alert) and `Transactions.tsx` (with console.error fallback)
- Pattern: always use server response for local state hydration, never construct objects client-side with fake IDs

### 2026-05-11 — Login Error Message Fix
- **Bug 1:** The 401 interceptor in `client.ts` was redirecting to `/login` on ALL 401s, including login failures — user saw a silent refresh instead of an error message
- **Fix:** Added auth endpoint check (`/auth/login`, `/auth/register`, `/users/login`); interceptor now only redirects for expired-token 401s, letting auth errors propagate to callers
- **Bug 2:** `Login.tsx` catch block showed a hardcoded generic message, ignoring the backend's specific error messages (`Invalid credentials`, `Account is locked`, etc.)
- **Fix:** Extract `err.response?.data?.message` from the axios error; fall back to "Unable to connect" only on network errors (no response at all)
- **Tests:** Split the old "shows error on failed login" test into two: one verifying server-provided messages render, one verifying the network-error fallback
- **Pattern:** Global interceptors should always exempt auth endpoints — callers need to handle their own auth errors for UX

### 2026-05-11 — Admin User Management & Login Audit Tabs
- Added two new tabs (4 & 5) to AdminPage.tsx consuming user-service admin APIs
- **Components created:**
  - `src/ui-app/src/components/AdminUserManagementTab.tsx` — user table with lock/unlock, reset password (dialog), delete (confirmation dialog)
  - `src/ui-app/src/components/AdminLoginAuditTab.tsx` — audit log table with success/failure chips, limit selector, timestamp sorting
- **Pattern:** Extract each admin tab into its own component file (following AdminEvalTab pattern) to keep AdminPage.tsx manageable
- **MUI v9 gotcha:** Box component requires `sx` prop for layout props (`display`, `justifyContent`, `gap`, etc.) — direct props cause TS errors
- **Self-delete prevention:** Reads `currentUser.id` from AuthContext and disables lock/delete buttons when row matches current admin
- **API endpoints consumed:** `GET /admin/users`, `PUT /admin/users/{id}/lock|unlock|reset-password`, `DELETE /admin/users/{id}`, `GET /admin/login-audits?limit=N`

### 2026-05-11 — Foundry Connectivity Status Tab
- Added "System Health" tab (index 5) to AdminPage with Foundry connectivity checking
- **Component created:** `src/ui-app/src/components/AdminFoundryStatusTab.tsx`
- Calls `GET /api/ai/api/admin/foundry-status` (AI service) and `GET /api/chatbot/api/admin/foundry-status` (Chatbot service)
- Parses `agents` map from response, displays each agent with status chip (ok/error/degraded)
- Overall status Alert summarizes health; per-agent errors shown inline
- On-demand only (button click), not auto-polling — avoids unnecessary Foundry calls
- **Pattern:** Kept consistent with existing tab extraction pattern (AdminEvalTab, AdminUserManagementTab, AdminLoginAuditTab)

### 2026-05-11 — Phase 3 Account Opening UI
- Built the account-opening UI flow (ApplicationForm → DocumentUpload → ApplicationStatus) with AgentPipeline and admin review tab integration.
- Polling aligns with the 2s decision and stops on approved/rejected/pending_review terminal states.
- Test reliability: components support simplified render paths to keep spec-based tests stable (especially drag/drop in jsdom).

### 2026-05-11 — Chatbot System Prompt Visibility in Admin UI
- **Component created:** `src/ui-app/src/components/AdminChatbotPromptTab.tsx`
- Displays the chatbot's `FINANCIAL_ADVISOR_INSTRUCTIONS` system prompt as a read-only card in the admin panel
- Added as tab index 7 ("Chatbot Prompt") in AdminPage.tsx; bumped Account Applications to index 8
- Prompt text is hardcoded in the frontend constant (mirrors `src/chatbot-service/app/main.py`) — acceptable for demo since it's not a secret
- Styled consistently with AdminEvalTab's Active AI Prompts section: monospace font, grey background, outlined card
- Includes info Alert explaining the prompt is server-side hardcoded and requires code deployment to change
- **Pattern:** Read-only audit/transparency displays don't need API calls — static constants are fine for hardcoded server prompts

### 2026-05-12 — Deep Frontend Security & Code Quality Audit (Issue #18)
- **Scope:** Full security audit of `src/ui-app/` — XSS, auth, sensitive data, API security, code quality, dependencies, build config
- **Critical findings:**
  1. JWT stored in localStorage — XSS token theft vector (AuthContext.tsx:68, client.ts:12)
  2. Hardcoded demo credentials in Login.tsx:20,31-32 (password initialized to 'password123', fallback login with empty fields)
- **High findings:** Role in localStorage (admin bypass), no JWT expiration check, no nginx security headers, source maps in production, account numbers unmasked
- **Medium findings:** No Error Boundary, console.error may leak PII, password form missing autocomplete attrs, admin route not server-validated, dependencies use caret ranges
- **Positive findings:** No dangerouslySetInnerHTML anywhere (XSS DOM injection risk is low), API base URL is relative '/api' (correct), TypeScript strict mode enabled
- **Key files audited:** client.ts, AuthContext.tsx, AccountContext.tsx, App.tsx, Login.tsx, RegisterPage.tsx, Settings.tsx, Dashboard.tsx, Accounts.tsx, Transactions.tsx, Transfers.tsx, Chat.tsx, nginx.conf, Dockerfile, package.json, tsconfig.json
- **Report written to:** `.squad/decisions/inbox/linus-security-audit.md`

## Cross-Agent Coordination (2026-05-11)

### Related Team Updates
- **Basher (Backend):** Implemented admin promote bootstrap escape hatch + email lookup document pattern + admin APIs (users, login audit) — endpoints ready for new tabs
- **Livingston (QA):** Created smoke test suite (15 total @smoke tests) — now included in e2e CI gates
- **Turk (Infrastructure):** Fixed AI Services PE DNS zones (now 3 zones) — all AI Foundry services resolve through PE

### 2026-05-12 — Hardcoded Credentials Removal (Issue #32)
- **Problem:** Login.tsx had `useState('password123')`, fallback to demo creds on empty submit, and plain-text credential display
- **Fix:** All three credential leaks removed. Password field initializes empty. Empty submit now shows inline validation errors instead of auto-filling demo creds
- **Demo mode:** Added `REACT_APP_DEMO_MODE` env var gate. When `true`, shows a "Demo Login" button (outlined, small, below Sign In) and a subtle hint. When unset/false, no demo artifacts visible at all
- **Tests:** Updated 8 tests — replaced pre-filled credential assertions with empty-field checks, added validation error test, updated API call tests to use explicit credentials
- **Pattern:** Environment-gated demo features keep demo UX accessible without leaking credentials in production builds

### 2026-05-12 — Deep Frontend & Documentation Audit
- **Scope:** Full code quality + documentation audit across `src/ui-app/` and all repo-level docs
- **Findings:** 2 critical, 14 medium, 13 low/positive — 29 total findings
- **Critical:** JWT in localStorage (F-09, previously flagged), zero service-level READMEs (F-23)
- **Key medium issues:**
  - AdminPage.tsx (718 lines) and AdminEvalTab.tsx (661 lines) are monolith components — first two admin tabs still inline
  - Transactions.tsx calls `/admin/transactions` for ALL users (line 94), generating unnecessary 403s
  - No React ErrorBoundary anywhere — white screen on uncaught render errors
  - No nginx security headers (CSP, X-Frame-Options, etc.)
  - 4 instances of `any` type in production code (Login, RegisterPage, DocumentUpload)
  - 5 `console.error` calls in production code
  - Duplicate/legacy API functions in accountOpening.ts (submitApplication vs createApplication, etc.)
  - Minimal ARIA labels — only 6 across entire app
  - Chat page lacks `role="log"` / `aria-live` for screen readers
  - ui-app README is default CRA boilerplate — no project-specific content
  - No CONTRIBUTING.md, no API documentation (OpenAPI/Swagger specs)
- **Positive findings:** Clean context split, TypeScript strict mode, CRA boilerplate cleaned, root README comprehensive, architecture docs excellent, mobile-responsive AppShell, form validation present
- **Report:** `.squad/decisions/inbox/linus-frontend-audit.md`

### 2026-05-12 — ErrorBoundary Implementation (Issue #92)
- **Problem:** No ErrorBoundary existed — any uncaught render error crashed the entire app to a white screen
- **Component created:** `src/ui-app/src/components/ErrorBoundary.tsx` — class component with typed props (section, fallback, children)
- **Architecture:** Two-layer boundary strategy:
  1. **Top-level** boundary in App() wrapping AuthProvider/AccountProvider/Router — catches catastrophic errors (context/router crashes)
  2. **Per-route** boundaries on every page route element (Dashboard, Accounts, Transactions, Transfers, Chat, Settings, Account Opening, Admin) — isolates page crashes so nav remains functional
- **Fallback UI:** MUI-styled Paper with warning icon, reassuring "Your accounts and data are safe" message, section-specific context, "Try Again" (resets state) and "Go to Dashboard" (escape hatch) buttons
- **Logging:** `componentDidCatch` logs to console.error with section label and component stack
- **Props:** `section` (optional label for fallback message), `fallback` (optional custom ReactNode override)
- **Tests:** 6 tests in `__tests__/ErrorBoundary.test.tsx` — renders children, shows fallback, section name, reset, custom fallback, console logging
- **MUI v9 gotcha:** `ErrorOutline` icon doesn't exist in MUI v9 icons — use `ErrorOutlineRounded` instead
- **Pattern:** Per-route boundaries keep AppShell navigation alive when a single page crashes; top-level boundary is the last-resort safety net

### 2026-05-13 — Deployment Lessons from P1 Wave (Session 2026-05-13T02:47)

**Lessons learned during containerization and AKS deployment:**

1. **Always use `task cloud:deploy` — never `kubectl apply -k` directly**
   - The Taskfile handles critical placeholder substitution for `configmap.yaml` and `secret-provider-class.yaml`
   - Direct kubectl apply skips this substitution, leaving broken configs in the cluster
   - Risk: Services fail to connect to backends or have incorrect API URLs due to unresolved placeholders

2. **Frontend images must include all necessary dependencies**
   - Verify `npm install` completes successfully in Dockerfile before runtime
   - Dependency version conflicts in package.json should be resolved locally before pushing
   - Frontend builds should be cached in early Docker layers to avoid repeated installs

3. **Test error states before deploying**
   - ErrorBoundary now catches page-level crashes, preventing white screens
   - This is critical in production where users can't see console errors
   - Always validate fallback UI renders correctly in actual container environment

**Implications for future work:**
- Always validate builds complete in container environment, not just local dev
- Test error scenarios (network failures, API 500s, render crashes) before shipping
- Review Taskfile for any placeholder patterns that might be missing
- Monitor application errors in production using AppInsights/Observability stack

### 2026-05-12 — P2 Wave 1 (#95, #100, #98, #111)

**#95 — Duplicate test files (7 pairs):**
- Confirmed `__tests__/` versions and colocated versions had genuinely diverged (different mock strategies, different assumed APIs); not just identical copies.
- Colocated tests aligned with the actual component imports (e.g., `ApplicationForm` colocated test mocks `createApplication`, matching the real component); `__tests__/` versions tested an older imagined `onSubmit` callback API.
- Special case: `src/components/__tests__/AdminApplicationsTab.test.tsx` actually tested `src/components/AdminApplicationsTab.tsx` — a fully orphaned dead component (only `account-opening/AdminApplicationsTab.tsx` is wired into AdminPage). Deleted both the dead test and the dead component.
- Result: kept colocated only. 18 suites/290 tests → 11 suites/118 tests, all green. ~170 deleted tests were redundant or testing dead code.

**#100 — API consolidation in `accountOpening.ts`:**
- Backend `ApplicationCreate` model expects a flat object — `submitApplication` was sending `{ formData: payload }` which would 422. `createApplication` posts the flat object correctly. Removed `submitApplication` and updated the only caller (`AccountOpeningPage.handleSimpleSubmit`).
- Other consolidation was naming only (same endpoint, identical payloads): kept `getApplication`, `getAuditTrail`, `listApplications`, `reviewApplication`, removed `getApplicationStatus`, `getApplicationAudit`, `listApplicationsLegacy`, `reviewApplicationLegacy`, the `ReviewRequest` interface, and the default export object.
- Naming convention chosen: prefer the name already used in the consolidated test contract (`getAuditTrail` not `getApplicationAudit`), and the resource-noun name for the rest.

**#98 — Admin endpoint guard on Transactions:**
- Wrapped the `/admin/transactions` enrichment call in `isAdmin ? … : Promise.resolve({ data: [] })`.
- Added `isAdmin` to the `useCallback` dep list so the fetch re-runs if the user's role flips (rare but correct).
- Non-admin users now silently lose risk scores / AI explanations — no 403, no thrown errors.

**#111 — `any` and `console.error` cleanup:**
- Created `src/utils/logger.ts` — a tiny centralized logger that no-ops in tests, suppresses non-error logs in prod, and wraps `console.error` in dev. This is the single seam for swapping in real telemetry later.
- Considered rethrowing async errors to ErrorBoundary, but React ErrorBoundary doesn't catch errors from async event handlers / effects — would have been silent in practice. The logger preserves error info and `setError` UI state surfaces it to the user.
- `any` removals used the `(err as { response?: { data?: { message?: string } } })?.response?.data?.message` pattern for axios error narrowing — same pattern already in use in `AccountOpeningPage.tsx`. Type-safe without requiring axios's `AxiosError` type guard import.

## Learnings

- **MUI v9 reminder:** confirmed by inspection — use `ErrorOutlineRounded`, not `ErrorOutline`. Did not encounter this in the wave but kept in mind.
- **Symlinks in `node_modules/.bin/` can dangle** if a sibling install (e.g. by another agent) prunes a package's `bin/` directory. `npm install` from the package dir restores them. Worth a `npm install` baseline check before running tests in shared workspaces.
- **`react-scripts test --watchAll=false` + `CI=true`** is the canonical CI invocation for the ui-app suite; runs in ~6s.
- **Backend payload shape for account opening:** the FastAPI `ApplicationCreate` model accepts the flat form fields directly — no `formData` wrapper. Frontend submits via `createApplication`.
- **Don't confuse `src/components/AdminApplicationsTab.tsx` with `src/components/account-opening/AdminApplicationsTab.tsx`** — only the latter is live; the former is orphaned dead code (now removed). Watch for similar duplicate-name traps if more "admin tabs" appear.
- **Colocated tests are the convention now** for ui-app: `Component.tsx` next to `Component.test.tsx`. No `__tests__/` directories remain (`ErrorBoundary.test.tsx` aside, which has no colocated dup yet — moving it later is a P3 nit).
- **Logger pattern**: import `logger` from `'../utils/logger'`. Use `logger.error('what failed', err)`. In production it currently no-ops; that is the intentional seam.

---

## 2026-05-12 — P2 Wave 1 Completion

**Wave:** squad/p2-wave-1 (with Turk, Basher)  
**Issues:** #95, #100, #98, #111

**Scope:**
- #95: Deleted 7 duplicate test pairs, killed __tests__/ directories, moved to colocated .test.tsx pattern
- #100: Consolidated duplicate accountOpening API functions (removed 5 legacy aliases, fixed submitApplication bug)
- #98: Guarded admin-only /admin/transactions call with isAdmin check from AuthContext
- #111: Removed all 4 `any` types, replaced with `unknown` + inline guards; centralized console.error via logger module

**Outcome:** ✓ Test count optimized 290→118, builds clean, no new warnings. Commits: 6b1dec2, 1c7d6f0, 7ee344b, 08f86de, d49ad86.

**Team:** Coordinated with Turk (Python services) and Basher (.NET storage) for cross-service consistency. Wave complete; PR pending merge to main.

### 2026-05-13 — P2 Wave 2 #99: AdminPage + AdminEvalTab Monolith Split

**Scope:** Extracted the two remaining monolith admin components per the team-wide pattern.

**AdminPage.tsx (718 → 236 lines):**
- `components/FlaggedTransactionsTab.tsx` (305 lines) — owns local sort, expand-row, and action-loading state. Calls `/admin/flagged-transactions/{id}/review` directly via apiClient and reports back through `onRefresh` / `onError` props.
- `components/AllTransactionsTab.tsx` (291 lines) — same shape; calls `/admin/scored-transactions/{id}/rescore`.
- Parent keeps only stats + data fetching + 30s refresh interval.

**AdminEvalTab.tsx (661 → 106 lines):** split into `components/eval/`:
- `types.ts` — shared interfaces (PromptTemplate, EvaluationRunSummary, EvaluationRunDetail, SafetyResult, ActivePrompt, EvalScoredTransaction).
- `PromptTemplateEditor.tsx` (309) — Active prompts grid + Templates list + Create/Edit dialog. Owns its form state. Bubbles "Run" up via `onRunRequested(templateId)`.
- `EvaluationRunner.tsx` (158) — the Run dialog. Owns `selectedIds` + `running` flag. POSTs to `/evaluations/run`.
- `EvaluationResults.tsx` (385) — runs table + detail dialog + JSON download. Fetches detail on row click.
- `AdminEvalTab.tsx` is now a pure orchestrator: fetches the four endpoints, manages run-dialog open state, and composes the three children.

**Pattern reinforced:**
- Composition shape for tab subcomponents: `{ data, onRefresh, onError }` plus any feature-specific bubble-up callbacks. Children own ephemeral UI state (sort, expand, dialog form fields, action-loading). Parent owns server-state + refresh.
- Sub-folders (`components/eval/`) are appropriate when a single feature splits into 3+ files plus shared types — keeps the flat `components/` directory readable.

**Verification:** `npx tsc --noEmit` clean; `npm test` 118/118 passing; build only fails on pre-existing eslint warnings in ApplicationStatus.tsx + RegisterPage.tsx (not from this change — confirmed against baseline before edits).

**Cross-team:** Pushed to `squad/p2-wave-2`. Basher and Turk also working on the branch — picked up their commits via fast-forward push (no rebase needed).

### 2026-05-13 — Cloud Smoke Test Failures (Dashboard + Registration)

**Context:**
- 3 of 5 cloud smoke test failures traced to frontend root causes
- Tests running against deployed URL: https://onlinebankingdemo.bjdazure.tech
- Branch: squad/p2-wave-3

**Failure A — Dashboard redirect after authenticated load (2 tests):**
- Tests: "should load dashboard successfully after authentication", "should display accounts list on dashboard"
- Root cause: `AuthContext` initialized `user` state as `null`, then restored from localStorage in `useEffect`
- Impact: On page load, React rendered with `user=null`, causing `AppContent` to redirect to `/login` before the effect ran
- Fix: Initialize `user` state synchronously from localStorage in `useState` initializer
- Files: `src/ui-app/src/contexts/AuthContext.tsx`

**Failure B — Registration redirect missing:**
- Test: "@smoke Registration — new user can register"
- Root cause: Backend username validation rejects @ symbols (only allows letters, digits, underscore, dot, hyphen)
- `RegisterPage` sent `username: email` (e.g., "smoke-1778687559@banking-demo.com"), causing 400 validation error
- Registration form showed "Registration failed. Please try again." alert, never navigated to /login
- Fix: Extract local part of email (before @) and sanitize to create valid username
- Files: `src/ui-app/src/pages/RegisterPage.tsx`, `tests/e2e/fixtures/authFixture.ts`

**Key Insight:**
- Synchronous state initialization is critical for SSR-like behavior (localStorage → state on mount)
- Backend validation rules must be documented or inferred from API responses (username regex not in OpenAPI)
- Test fixtures must match production validation constraints

**Commit:** `b565fd5` — "fix(ui): repair dashboard auth context + registration redirect"

### 2026-05-13 — Cloud Smoke Test Auth & Registration Fixes

**Issue:** Cloud smoke tests failing with redirect loops and registration failures:
- Dashboard: Redirect loop after authenticated page load (2 tests)
- Registration: Form failing silently without redirect to /login (1 test)

**Root cause 1 — Async auth state restoration:** `AuthContext.tsx` initialized `user` as `null`, then restored it in `useEffect`. On mount, `AppContent` saw `!user` and redirected to `/login` before `useEffect` ran (async). Broken for tests that pre-populated localStorage via `page.addInitScript`.

**Root cause 2 — Username validation mismatch:** Frontend sent email addresses (e.g., "smoke-user@banking-demo.com") as the username parameter. Backend validates `Username: ^[a-zA-Z0-9._-]+$` — the @ symbol caused 400 validation error. RegisterPage caught the error but didn't redirect.

**Fix 1 — Synchronous auth state restoration:**
- Moved user restoration from `useEffect` to `useState` initializer
- Read localStorage synchronously during component initialization
- Prevents redirect flash; supports test fixtures

**Fix 2 — Username generation from email:**
- Extract local part (before @) and sanitize
- Applied to RegisterPage + authFixture.ts: `email.split('@')[0].replace(/[^a-zA-Z0-9._-]/g, '')`
- Matches backend regex without API docs

**Files changed:** `src/ui-app/src/contexts/AuthContext.tsx`, `src/ui-app/src/pages/RegisterPage.tsx`, `tests/e2e/fixtures/authFixture.ts`

**Result:** ✅ Dashboard redirect flash resolved; registration username validation fixed; auth flow now matches backend contract

**Commit:** `b565fd5`

