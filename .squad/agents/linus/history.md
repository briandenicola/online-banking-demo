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

**2026-05-14 Scribe note (Basher's eval fix):** Prompt Evaluation UI errors now have meaningful messages. Fixed two bugs: (1) FastAPI @property serialization → C# KeyNotFoundException, (2) ai-service incomplete-eval silent-success. See decisions.md "Eval Pipeline — KeyNotFoundException + Incomplete Result Handling".

**2026-05-15 Linus note (Account Opening State Machine):** Customer status page now uses shared ApplicationStages component. Retry cap enforced at 1 (stageAttempts < 2). ErrorOutlineRounded used instead of ErrorOutline (MUI v9). Polling stops on terminal status.

**2026-06-05 Scribe note (Turk's UI App Port Fix):** nginx port mismatch resolved. Rebuilt ui-app image from MCR-based Dockerfile (Azure Linux nginx:1.28 on 8080). Added CSS module type declarations (custom.d.ts). Fixed Dockerfile/nginx.conf for Azure Linux permissions (no /var/cache/nginx, error_log stderr). Updated tasks/Taskfile.local.yml with `--build` flag to prevent stale images during dev. UI now reachable on localhost:3000. See decisions.md "UI App Port Mismatch from Stale Docker Image".

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


### 2026-05-13 — Registration Smoke Failure (Stale Bundle / :latest Tag Trap)

**Context:** After commit b565fd5 ("repair dashboard auth context + registration redirect"), 20/21 smoke tests passed. The Registration test continued to fail reliably with `waitForURL('**/login')` timeout.

**Investigation:**
- Pulled the live `main.<hash>.js` from https://onlinebankingdemo.bjdazure.tech and grepped the registration POST payload.
- Bundle showed `post("/users/register",{username:a, firstName:e, lastName:n, email:a, password:l})` — both `username` and `email` mapped to the **same minified variable `a`**, which is the raw email state. The sanitization regex `[^a-zA-Z0-9._-]` was absent from the bundle.
- That matches the **pre-b565fd5** source (`username: email`), confirming the deployed bundle was stale.
- API replay with `email: <local-part-only>` returned `400 "The Email field is not a valid e-mail address."` — exact root cause of the "Registration failed. Please try again." alert seen in the Playwright snapshot.

**Why the fix didn't deploy:**
- ACR had a newer `ui-app:latest` digest (16:44 UTC) than the running pod (started 14:01 UTC on the older 13:57 digest).
- Kustomize manifests pin `ui-app:latest` (no SHA, no per-build tag). `task cloud:deploy` runs `kubectl apply -k`, which is a **no-op** when the manifest hasn't changed — so even after `cloud:build:ui-app` pushed a fresh image, the deployment spec didn't roll and pods never re-pulled.
- `imagePullPolicy: Always` only matters on **pod creation**; without a pod restart, an updated `:latest` is invisible.

**Fix:**
1. `task cloud:build:ui-app` — rebuilt + pushed (digest `sha256:55794a77...`).
2. `task cloud:deploy` — applied manifests (no-op for ui-app spec, but config/secrets refreshed).
3. `kubectl -n banking-demo rollout restart deployment/ui-app` — forced new pod to pull fresh `:latest`.
4. Verified live bundle: new minified POST is `{username:t, ..., email:a, ...}` — distinct variables, proving the `.replace(...)` survived minification this time.
5. Registration smoke passes (2.2s).

**Lessons:**
- **`:latest` + `kubectl apply` ≠ rolling deploy.** When kustomize image tags don't change, Apply alone won't restart pods — even with `imagePullPolicy: Always`. The deploy task needs either (a) digest-pinned tags per build, or (b) an explicit `rollout restart` step. This bit us once already and will keep biting until fixed in the Taskfile.
- **Always sanity-check the served bundle** when a frontend smoke fails post-deploy. `curl` the JS from `asset-manifest.json` and grep for a known marker from the latest source — it takes 30 seconds and immediately tells you "deployed code ≠ source".
- **Terser variable aliasing risk:** when two adjacent shorthand object properties (`{username, email}`) are derived from the same source value, the minifier may emit them with the same variable name in the output. The b565fd5 fix (introducing a derived `const username = ...replace(...)`) breaks that aliasing because `username` and `email` now hold different values.

### 2026-05-13 — Coordinator Integration: Rollout Restart in cloud:deploy (commits e57d5f0, 1a989f2)

**Pattern:** The Coordinator has permanently integrated `kubectl rollout restart deployment/<svc>` into the `task cloud:deploy` target as of commit e57d5f0. This eliminates the manual `kubectl rollout restart` workaround after every cloud build/deploy cycle.

**Historical context:** Your stale-bundle trap discovery and the manual rollout restart fix prompted the Coordinator to bake this into the Taskfile itself. `:latest` image tags no longer require manual pod bouncing — `task cloud:deploy` now handles it automatically.

**For you:** Any service you build/deploy via `task cloud:deploy` will now automatically restart pods as part of the deploy job. This means your next smoke test verification should see new bundles on deploy without requiring the manual `kubectl rollout restart` workaround.

**Additional refactor (commit 1a989f2):** The Taskfile's `NAMESPACE` variable is now hoisted to task-level scope, eliminating hardcoded `banking-demo` strings throughout the deploy targets. This makes it easier to test against different namespaces.

**Files that changed (Taskfile):**
- Added rollout restart commands for ui-app, user-service, account-service, transaction-service, transfer-service, ai-service, chatbot-service, budget-service, account-opening-service, prompt-eval-service post-kustomize-apply
- Hoisted NAMESPACE to global task var

**Verification:** Your next E2E smoke run should pick up the deployed bundle immediately after `task cloud:deploy`, no manual restart needed.


### 2026-05-13 — #119 + #120 Active AI panel + Avg Risk Score (P2 wave 3)

**#119 — Avg Risk Score = 1,778,591,506.40**
- Cause is backend, not frontend. `AdminPage` renders whatever `/api/admin/stats`
  returns; backend averages a Redis sorted-set whose score *should* be the
  clamped 0–1 `assessment.riskScore` (`anomaly_service.py:617`) but was
  poisoned with timestamp values from before the Foundry agents were wired
  (#118). Magnitude `1.78e9` ≈ `time.time()` for 2026 — dead giveaway.
- Frontend defensive fix: added `formatRiskScore()` in `AdminPage.tsx`
  that returns `'—'` for any value outside `[0, 1]` (also guards NaN/±∞).
  The dashboard will never advertise a 10-digit "risk score" again, even
  if more bad data sneaks in.
- Real fix is a Redis cleanup of `scored-transactions` — flagged for
  Brian/Basher in the issue comment.

**#120 — Active AI Prompts blank + Disabled**
- Confirmed backend `/api/admin/prompts` (`src/ai-service/app/routes/api.py:285`)
  returns only `{name, type, enabled}` — no `systemPrompt` field at all.
  That's why every card body is empty. The Disabled badge logic
  (`prompt.enabled ? 'Active' : 'Disabled'`) is not inverted; if the badge
  reads Disabled, that's what the analyzer object reports.
- Frontend changes: made `ActivePrompt.systemPrompt` optional in
  `components/eval/types.ts`; `PromptTemplateEditor.tsx` now renders an
  italic placeholder with a hint pointing at #120 when the field is
  missing, instead of an empty gray bar.
- Backend fix (add `systemPrompt: analyzer.SYSTEM_PROMPT` to the response)
  flagged for Basher in the issue comment. Issue stays open.

**Deploy verification (don't trust `:latest` apply alone):**
- `task cloud:deploy` now bakes in `kubectl rollout restart deployment -n {{.NAMESPACE}}`
  (good — no more stale-bundle traps like the b565fd5 incident).
- Pulled the live `main.<hash>.js` and grepped for the new marker
  string `"Prompt body not returned"` (present, count 1) and the
  minified `Number.isFinite(...)` from `formatRiskScore` (present).
  Bundle deploy verified end-to-end, not just by trusting kubectl.

## Learnings
- **Backend-bug? Add a frontend defensive guard anyway.** The avg-risk
  display was correct *given the data*, but the user-visible output was
  garbage. A `formatRiskScore` clamp is a few lines and prevents
  recurrence regardless of who poisons the source. Pattern: every
  numeric tile that has a known domain ([0,1], [0,100], non-negative)
  should have a tiny "in-range or em-dash" formatter.
- **Field-missing vs field-wrong.** When a UI renders blank, the
  null-coalesce / placeholder guard is just as important as fixing the
  contract — it's how the user finds out *why* it's blank instead of
  staring at an empty gray rectangle.
- **TypeScript field optionality is a contract debugger.** Marking
  `ActivePrompt.systemPrompt?: string` immediately surfaced "the API
  doesn't actually send this" — the kind of thing that'd otherwise be
  buried in a runtime undefined.
- **Bundle-grep verification habit is paying off.** Same 30-second
  `curl asset-manifest.json | grep marker` flow caught the stale
  registration deploy two sessions ago; this time it confirmed the new
  bundle landed before I left the issue alone.

## Historical Context (2025)

**Note:** This section summarizes learnings from pre-2026 UI audits and fixes. See dated subsections below for full details.

### 2025 Audit Summary

From frontend code quality audits conducted in 2025-07:
- **UI patterns:** Established React component hierarchies, state management approach, styling conventions (MUI v9)
- **Key fixes:** Transaction endpoint integration, Nginx proxy issues, account API alignment, login error handling
- **Best practices:** Input validation, error boundaries, accessible forms, responsive layouts, test fixtures
- **Infrastructure:** Docker healthchecks, container hardening, pod security policies

For specific dates and detailed fixes from these entries, refer to the dated learning sections (###) above.


## Learnings — 2026-05-13 — issue #127 (Account Opening 422 + React #31)

**The FastAPI 422 `detail` array gotcha** — Pydantic validation errors come back as
`{ detail: [{ type, loc, msg, input, ctx }, ...] }`. The previous `resolveSubmitError`
returned `error.response.data.detail` directly, which set React state to an array of
objects. Rendering that in JSX trips React error #31 (objects are not valid as a
React child) and falls through to ErrorBoundary, producing a white screen. **Always
coerce to string before `setSubmitError(...)`** — and always type the resolver as
`(error: unknown) => string` so the compiler catches the regression.

This pattern is going to bite us again on every other Pydantic-validated POST:
- `account-service` (transfer/account create endpoints — .NET ProblemDetails shape, but the form-level `setError` fallback is the same risk)
- `transfer-service` (.NET — ProblemDetails returns `errors: { field: ["msg"] }`)
- `chatbot-service`, `budget-service`, `ai-service`, `account-opening-service` (all FastAPI — array `detail`)

**Reusable pattern landed:** `src/ui-app/src/api/errors.ts` exports `resolveApiError(error, fallback)`
which handles: string detail, array detail (FastAPI), `message`/`title`, ProblemDetails
`errors` map. Tested in `errors.test.ts`. Use it from every form's catch block.

**Wire-vs-form payload separation** — the form's `FormState` / `ApplicationFormData`
is a flat UI-friendly shape. The backend wire contract (`ApplicationCreateRequest`)
is nested. Keep them as separate TypeScript types and convert at the API boundary
(`buildCreateRequest`). Conflating them is what let the contract drift unnoticed.


## Learnings — 2026-05-13 — issue #129 (Phone Mask + Email Pre-fill)

**Hand-rolled input formatters beat libs for simple cases** — The phone mask (restrict
chars + apply US format) is ~30 lines total. React Input Mask / IMask would add 50KB+
to the bundle for the same result. Keep the formatter inline, under 40 lines. Backend
regex: `^\+?[\d\s\-().]{7,30}$` — validate on blur for instant feedback, but still
defer to server-side 422 as the source of truth. Defense-in-depth: client restricts,
server enforces.

**Auth context pre-fill pattern** — Use `useAuthContext()` from
`src/ui-app/src/contexts/AuthContext.tsx`. For email pre-fill, do it in state init
(not `useEffect`) to avoid flicker:
```typescript
const { user } = useAuthContext();
const [values, setValues] = React.useState(() => {
  const initial = resolveInitialState(initialData);
  if (!initial.email && user?.email) {
    initial.email = user.email;
  }
  return initial;
});
```
Defensive: fallback to empty if `user?.email` is null. Field remains editable.

**Test harness must match runtime context** — Components using `useAuthContext` throw
"must be used within AuthProvider" in tests. Wrap the component in `<AuthProvider>` in
`renderForm()` (or each test case). Pattern is consistent across the codebase — no
mocks, just wrap in the real provider. 15/15 tests passed after adding the wrapper.

**onBlur validation for format checks** — Phone validation triggers on blur so the user
isn't harassed mid-type, but still sees the error before submitting. Pattern:
`handlePhoneBlur()` sets `errors.phone` if `validatePhoneFormat(values.phone)` fails.
Client-side regex must match backend regex exactly to avoid false positives.

### 2026-05-13 — Form Pre-fill from Auth Context (#129)
- **Pattern:** Use `useAuthContext()` hook for reactive form initialization without flicker
- **Implementation:** State-init pattern via `React.useState(() => { ... const { user } = useAuthContext(); ... })` 
- **Key:** Initialize in the state-init callback (not `useEffect`) to avoid re-render on mount
- **Defensive:** Always check `user?.email` and fall back to empty string (`user?.email || ''`) — avoid assuming auth state exists
- **Test wrapper requirement:** Any component using `useAuthContext()` must be wrapped in `<AuthProvider>` during tests or will throw "must be used within AuthProvider"
- **Reusable:** For future forms needing user-derived pre-fills (email, firstName, phone, etc.), import `useAuthContext` from `src/ui-app/src/contexts/AuthContext.tsx` and follow this pattern
- **Phone input mask:** Hand-rolled ~30 lines. Formatter restricts to `[\d\+\-() .]`, applies US mask `(555) 123-4567` unless international (`+`), strips invalid chars on paste. Validator checks backend regex `^\+?[\d\s\-().]{7,30}$` on blur.

### 2026-05-13 — Multi-Select / Singular File Upload Binding (#130)
- **Problem:** Frontend allowed `<input multiple>` while backend FastAPI `file: UploadFile = File(...)` (singular) only processes one file — rest silently dropped
- **Root cause:** FormData.append('file', f) loop appended multiple 'file' keys, but FastAPI non-list binding only reads the first
- **Solution (Option 3):** Block multi-select at UI level. Removed `multiple` attribute from input, changed `uploadDocuments()` API signature from `File[]` → `File`, defensive slice in `handleFileSelection()` to guard against drag-drop bypassing input attribute
- **Files changed:**
  - `src/ui-app/src/api/accountOpening.ts` — uploadDocuments() now takes single `File` parameter
  - `src/ui-app/src/api/accountOpening.test.ts` — test calls updated to pass single file instead of array
  - `src/ui-app/src/components/account-opening/DocumentUpload.tsx` — removed `multiple`, updated copy ("Drop a file here", "Select File"), sliced `files[0]` in upload call
- **Gotcha:** HTML input `multiple` can be bypassed by drag-drop — always defensively slice `selected.length > 1 ? [selected[0]] : selected` in drop handlers
- **Rationale:** Backend contract is singular (one file per request). Multi-file support would require backend changes (`file: list[UploadFile] = File(...)`). Simpler to match frontend to actual backend behavior than risk silent failures.

---

### 2026-05-14T02:03:23Z: Cross-team notification — #137/#130 resolved

**By:** Scribe (Orchestration)  
**Topics:** FoundryAgent SDK contract, unified fix scope

Issues #137 (eval failures) and #130 ("AI Calls Today" counter stuck at 0) are now CLOSED and verified in production. Both traced back to the same root cause: FoundryAgent constructor signature drift.

**New contract:** When instantiating any `FoundryAgent(...)`, pass model via `default_options={"extra_body": {"model": "<deployment_name>"}}` — do NOT pass `model=` as a direct kwarg (SDK 1.2.2 rejects it).

**Scope of fix:**
- account-opening-service: all 4 FoundryAgent constructors fixed
- ai-service: all 3 FoundryAgent constructors fixed (risk_agent, categorizer_agent, eval_agent)

**Prevention:** Both services now have runtime `TestFoundryAgentSignatureContract` tests that run on every pytest invocation. Catch signature drift on next SDK pin bump.

**Impact on #135/#136 work:** No impact. Your frontend work proceeds normally; backend #135-PR1/PR2/PR3 execution is unblocked by the answers to Danny's 3 planning questions (see .squad/decisions.md).

---

**2026-05-14 16:57 Scribe:** Heads-up: #141 filed — Foundry Managed VNet migration plan from Danny. See decisions.md for context.

### 2026-05-15 — Account Opening State Machine UI (#135 + #136)

**Scope:** Customer-facing status page with retry UX and AI explanation rendering per Danny's coordinated plan.

**Implementation:**

1. **TypeScript Schema Extensions:**
   - Added `'failed'` to `ApplicationStatus` type
   - Added `LastError` interface: `{ stage, code, message, retryable, occurredAt, attempt, correlationId }`
   - Extended `ApplicationResponse` with `lastError`, `stageAttempts`, `failedStage`, `customerOutcome`, `customerExplanation`, `customerExplanationGeneratedAt`
   - Added `resubmitApplication()` API call: `POST /applications/{id}/resubmit` → 200 success, 409 conflict

2. **Shared Component Extraction:**
   - Created `ApplicationStages.tsx` — reusable stage stepper + detail cards
   - Refactored `AgentPipeline.tsx` to delegate to `ApplicationStages` (eliminated 146 lines of duplication)
   - Both admin and customer views now share stage rendering logic

3. **Customer Status Page (`CustomerApplicationStatusPage.tsx`):**
   - Polls `GET /applications/{id}` every 2s until terminal status
   - Renders stage progress with stepper + status icons (CheckCircle, Error, Autorenew, HourglassEmpty)
   - **Retry UX:** Shows "Retry" button when `status === 'failed'` AND `lastError.retryable === true` AND `stageAttempts[failedStage] < 2` (retry cap = 1)
   - **Retry Cap Enforcement:** Hides button when `stageAttempts[failedStage] >= 2` OR `lastError.retryable === false`; shows "Contact support" message instead
   - **409 Conflict Handling:** Catches 409 from resubmit endpoint, displays `message` from response body
   - **AI Explanation Display:** Renders `customerExplanation` when terminal (approved/rejected/pending_review) with appropriate emoji + styling
   - **Error Rendering:** Uses `resolveApiError()` helper to handle FastAPI 422 validation array (prevents React error #31)

4. **Routing & Flow:**
   - Added `/applications/:id/status` route in `App.tsx` (authenticated users, not admin-only)
   - Simplified `AccountOpeningPage.tsx` to 2-step flow (form → upload); removed processing/status steps
   - After document upload, redirect to customer status page: `navigate(\`/applications/\${application.id}/status\`)`
   - Customer no longer sees in-progress UI on submission page — redirected to dedicated polling page

5. **ApplicationStatus.tsx Updates:**
   - Added `'failed'` to terminal statuses array
   - Mapped `'failed'` to error color (red) and message: "We encountered an issue processing your application."

**Key Patterns Followed:**

- **Icon Choice:** Used `ErrorOutlineRounded` instead of `ErrorOutline` (MUI v9 — per skill: no `ErrorOutline` icon)
- **Error Handling:** All API errors passed through `resolveApiError()` to avoid raw object rendering
- **Polling Lifecycle:** `useEffect` with `setInterval` + cleanup; stops when `isTerminal(status)` returns true
- **Retry Logic:** Client-side validation matches server-side cap: `stageAttempts[stage] < 2` (1 retry allowed)
- **Terminal Checks:** `['approved', 'rejected', 'pending_review', 'failed'].includes(status)` — includes new `'failed'` state

**Outcome:**
- Build passes with TypeScript strict mode (`npm run build` → 241.18 KB gzip, warnings only)
- 6 commits pushed to `origin/squad/135-136-account-opening-state-machine`
- No backend modifications (frontend-only as required)
- Ready for consolidation with Basher (backend) + Livingston (tests)

**Contract Dependencies (awaiting Basher's push):**
- `POST /applications/{id}/resubmit` endpoint: 202 accepted, 409 conflict with `{error, message}` body
- `ApplicationResponse` fields: `lastError`, `stageAttempts`, `failedStage`, `customerOutcome`, `customerExplanation`, `customerExplanationGeneratedAt`
- Backend retry cap enforcement: `stageAttempts[stage]` must match UI cap (max=2, i.e., 1 retry)

**Known Gaps:**
- No E2E tests yet (blocked on Livingston's Playwright suite)
- AI explanation generation logic lives in backend (out of scope for Linus)
- Admin override to reset attempts not implemented (Danny confirmed out-of-scope)

**Reusable Patterns:**
- `ApplicationStages.tsx` can be reused in any account-opening UI (admin detail dialogs, customer dashboards)
- `resolveApiError()` pattern now documented in history — always use for FastAPI 422 responses
- Retry cap check pattern: `(attempts[stage] ?? 0) < 2` — safe against undefined stageAttempts dict

**Build Verification:**
```bash
cd src/ui-app && npm run build
# → Compiled with warnings (exhaustive-deps only, not blocking)
# → 241.18 kB gzip (-212 B from previous build)
```

**Commits:**
1. `feat(ui): #136 Add TypeScript types for state machine fields` (743d627)
2. `feat(ui): #136 Extract shared ApplicationStages component` (42ea60f)
3. `feat(ui): #136 Refactor AgentPipeline to use shared component` (9d86b7f)
4. `feat(ui): #136 Add customer application status page` (2a8f5b7)
5. `feat(ui): #136 Add customer status page route` (51f324d)
6. `feat(ui): #136 Redirect to customer status page after upload` (f04f407)
7. `feat(ui): #135 Add 'failed' status support to ApplicationStatus` (8e60df4)

---

## 2026-05-14: Frontend Implementation — Issues #135 + #136

**Batch:** Coordinated account opening resubmit (#135) + customer status page (#136) implementation

**Role:** Frontend Dev — implemented React/TypeScript UI for customer status page and retry UX

**Component Architecture:**
- Extracted ApplicationStages.tsx as shared component (147 lines)
- Eliminates 68% duplication between admin (AgentPipeline) and customer views
- Visual consistency: stage rendering (stepper, status icons, details) now unified

**CustomerApplicationStatusPage:**
- 283 lines with polling + retry UX
- 2s polling interval until isTerminal(status)
- useEffect cleanup prevents memory leak
- useRef prevents stale closure issues

**Retry Button Visibility Logic:**
- Visible when: status='failed' AND lastError?.retryable=true AND stageAttempts?.[failedStage]<2
- Implements retry cap per Brian's directive (max 1 retry = 2 total attempts)
- Edge cases: handles missing stageAttempts dict key (defaults to 0)

**AI Explanation Display:**
- Renders customerExplanation ONLY for terminal statuses
- One-shot generation at finalization (never regenerated)
- Visual design: approved (green), rejected (red), pending review (yellow), failed (neutral)

**Error Handling:**
- resolveApiError() helper for all API calls
- Handles FastAPI 422 validation arrays (coerces to human-readable strings)
- 409 conflict: display backend message, hide retry button

**MUI v9 Compliance:**
- Uses ErrorOutlineRounded (v9 removed ErrorOutline)

**Routing Integration:**
- Redirect to /applications/:id/status after document upload
- Enables bookmarking, sharing, cleaner separation of concerns

**TypeScript Types:**
- LastError interface (stage, code, message, retryable, occurredAt, attempt, correlationId)
- Extended ApplicationResponse (lastError, stageAttempts, failedStage, customerOutcome, customerExplanation)

**Status:** ✅ Complete; build verified (npm run build, non-blocking exhaustive-deps warning)  
**Commits:** 743d627, 42ea60f, 9d86b7f, 2a8f5b7, 51f324d, f04f407, 8e60df4  
**Branch:** squad/135-136-account-opening-state-machine  
**Files Changed:** 7 files, +515 -230 lines (net +285)

**[2026-06-05 Scribe Note]** Two-setup gateway design: Local docker-compose uses dedicated gateway service + local nginx override (infrastructure/local/); Azure/AKS uses Istio. Do NOT add local gateway logic to image-baked src/ui-app/nginx.conf (it ships to cloud). See decision: Local API Gateway vs Azure Istio Gateway.

---

## Learnings

### 2026-06-18: Webpack 5 fullySpecified ESM Resolution Issue

**Root Cause:**
MUI v9's ESM build (`.mjs` files) imports `react-transition-group/TransitionGroupContext` without a file extension. Webpack 5 in react-scripts 5.0.1 enforces `fullySpecified: true` by default for strict ESM modules, causing the build to fail with:
```
Module not found: Error: Can't resolve 'react-transition-group/TransitionGroupContext'
BREAKING CHANGE: The request failed to resolve only because it was resolved as fully specified
The extension in the request is mandatory for it to be fully specified.
```

**Fix Applied:**
Installed `@craco/craco` (^7.1.0) as devDependency and created `craco.config.js` to override webpack config without ejecting:
```javascript
module.exports = {
  webpack: {
    configure: (webpackConfig) => {
      webpackConfig.module.rules.push({
        test: /\.m?js$/,
        resolve: {
          fullySpecified: false,
        },
      });
      return webpackConfig;
    },
  },
};
```

Updated package.json scripts to use `craco` instead of `react-scripts` for start/build/test commands.

**Files Changed:**
- `src/ui-app/craco.config.js` (created)
- `src/ui-app/package.json` (scripts section + devDependencies)
- `src/ui-app/package-lock.json` (auto-updated by npm install)

**Validation:**
`npm run build` now compiles successfully. Build output: 244.06 kB gzipped main.js bundle, deployed to build/ folder.

**Why This Works:**
CRACO is the standard, non-ejecting solution for Create React App webpack overrides. Setting `fullySpecified: false` for `.m?js` files allows webpack to resolve extensionless imports from ESM modules (MUI's .mjs) while maintaining all other CRA defaults.

### 2026-06-18: Dependabot PR Resolution - Transitive Security Bumps via npm Overrides

**Task:**
Resolved 3 Dependabot PRs for src/ui-app:
- PR #215: npm-minor-patch group (@mui/material 9.0.0→9.1.1, @mui/icons-material 9.1.0→9.1.1, @types/node 25.9.2→25.9.3, axios 1.17.0→1.18.0)
- PR #220: form-data security bump (transitive via axios, required >= 4.0.6)
- PR #221: launch-editor security bump (transitive via webpack-dev-server, required >= 2.14.1)

**Approach:**
1. Edited package.json with the 4 direct dependency bumps from PR #215
2. Ran `npm install --legacy-peer-deps` (required for react-scripts 5.0.1 peer conflicts)
3. Verified transitive deps with `npm ls form-data launch-editor`:
   - form-data: 4.0.5 (needed 4.0.6) and 3.0.4 (needed 3.0.5)
   - launch-editor: 2.13.2 (needed 2.14.1)
4. **Added npm overrides** to package.json to force the security versions:
   ```json
   "overrides": {
     "form-data": "4.0.6",
     "launch-editor": "2.14.1",
     ...
   }
   ```
5. Re-ran `npm install --legacy-peer-deps` to apply overrides

**Why Overrides (Not `npm update`):**
Attempted `npm update form-data launch-editor --legacy-peer-deps` first, but these are deep transitive deps locked by react-scripts 5.0.1's own package-lock. The `overrides` field in package.json is the canonical npm 8+ solution for forcing transitive dependency versions without forking upstream packages.

**Validation:**
- `npm ls form-data launch-editor` confirmed both at required security versions (4.0.6 overridden, 2.14.1 overridden)
- `npm run build` compiled successfully with craco (244.99 kB gzipped main.js, +932 B vs previous)
- Vulnerabilities reduced from 35→33 (form-data and launch-editor CVEs resolved)
- MUI 9.1.1 + axios 1.18.0 work with existing craco fullySpecified fix

**Files Changed:**
- `src/ui-app/package.json` (4 version bumps + 2 override entries)
- `src/ui-app/package-lock.json` (regenerated, 10 packages changed first pass, 3 on override pass)

**Key Insight:**
npm overrides are the correct mechanism for security bumps of transitive deps when upstream (react-scripts) hasn't published a fix yet. They're declarative, auditable, and persist across installs. The craco build continues to work flawlessly with MUI 9.1.1.

## Learnings

### 2026-09-04 — Banker Copilot Frontend Design Spike (docs/design/banker-copilot-ui.md)

Design-only spike for the "Banker Copilot" epic — an agentic harness for the banker/admin
experience. Deliverable: `docs/design/banker-copilot-ui.md` (9 sections). No code changed.

**Framing decision that drove everything:** this is a WORK SURFACE, not a chatbot. Three panes
(task queue / live plan-trace / artifact canvas) with the command input demoted to a ~48px strip
at the bottom. Design test applied to every screen: *remove the text input — is the surface still
usable?* Must be yes. That single layout choice is what stops it reading as `Chat.tsx` v2.

**Existing-code findings that shaped the design:**
- `api/client.ts` attaches the bearer token from `localStorage` via an axios interceptor.
  Native `EventSource` **cannot set headers**, which would force the token into a query string
  (nginx access logs, browser history, APM spans). Therefore: **SSE over `fetch` +
  `ReadableStream`**, not `EventSource`, not WebSocket. Traffic is ~all server→client; the rare
  client→server events (sign/deny) are high-stakes and want real HTTP status codes + idempotency
  keys, which argues against a socket.
- `infra/local/gateway.nginx.conf` has **no `proxy_buffering off`** on any `/api/` location.
  Without it nginx buffers the whole SSE response and the "live" trace arrives as one lump at the
  end. Flagged as the single highest-risk non-frontend dependency for the epic.
- `components/account-opening/ApplicationStages.tsx` + `AgentPipeline.tsx` are the direct
  ancestors of the trace node (same `pending/in_progress/completed/failed` union, same
  confidence + reasoning + timestamp card). Reused the *vocabulary*, not the layout — that's a
  horizontal `Stepper`, the trace is a vertical recursive tree.
- `formatRiskScore` now exists in `AdminPage.tsx` and is about to be needed a third time. Should
  be promoted to `utils/format.ts` rather than copy-pasted again.
- `Chat.tsx`'s unconditional `scrollIntoView` on every message is an autoscroll bug I explicitly
  did not repeat: the trace releases follow-the-tail on any user scroll-up and offers a
  `↓ N new steps` pill.

**Admin tabs disposition** (3 buckets, phased, `/admin` stays alive): *subsumed* (Flagged Txns,
All Txns, Account Applications → become task sources + agent tools, tabs demoted to "Classic
Admin"); *retained unchanged* (Chatbot Prompt, AI Eval, Login Audit, System Health — config/ops
surfaces with no per-item decision loop); *explicitly L3* (User Management — agent may not even
propose; typing "promote X to admin" yields a refusal card). Key argument: the agent's
credibility depends on the banker being able to verify its claims. Removing the ground-truth
tables on day one makes the agent unfalsifiable.

**aria-live for a high-frequency live region — the subtle bit.** Naive `aria-live="polite"` on
the trace tree announces every tool call and timer tick; the screen-reader user turns it off,
which is worse than nothing. Correct pattern: the **visual region and the announced region are
different regions.** Trace tree is `aria-live="off"` + `role="tree"` + `aria-busy` (explorable on
demand); a separate visually-hidden region gets **coalesced 2500ms plan-level summaries**.
`assertive` reserved for exactly three events: approval required, approval voided, agent
disagreement. Countdowns are `role="timer"` with `aria-hidden` digits + discrete announcements at
5:00/1:00/0:30.

**State management — no new dependency.** Repo uses plain React Context + CRA/craco; adding
Redux/Zustand for one surface isn't a trade worth making. Instead: external mutable store +
`useSyncExternalStore` + per-node version counters + a single `requestAnimationFrame` coalescing
frame (bursts of 40 events in 16ms → one render pass) + one shared 1s ticker for all countdowns.
Reducer is a pure `(state, event) => state`, which also buys a deterministic fixture-driven
**demo mode** that survives a bad conference network. Build that in week one, not week six.

**Anti-approval-fatigue is a design problem, not a discipline problem.** Concrete mechanisms I'd
ship: stakes-scaled dwell timers (0s batch → 25s + written justification for L2 disagreement,
full reset after a payload void); `IntersectionObserver` gate requiring material fields to
actually be scrolled into view; batch cap of 10 within a single action type under threshold,
never L2; randomised 7% transcribe-one-fact spot checks; per-session approval meter with a soft
pause card; deliberate visual variance on irreversible items to break rubber-stamp muscle memory.
Explicitly rejected: hard blocks (get worked around via a second login), CAPTCHAs, mandatory
free-text on every item (produces "ok" fourteen times and devalues the field where it matters).

**Signature-void UX.** On `approval.voided` the card must NOT quietly update — that's precisely
the TOCTOU the payload-hash design exists to prevent. Old card freezes, greys, stamps VOID, stays
in history; new card shows a **field-level** diff (not text diff) with material changes
highlighted; dwell resets to full; first two lines of copy answer the banker's actual first fear:
*"Nothing was executed."*

**Reusable pattern extracted:** `.squad/skills/streaming-agent-trace-ui/SKILL.md`.

---

#### Cross-cutting findings from Banker Copilot ideation (2026-09-04)

**Finding 1: Single shared JWT audience is the repo's biggest latent authorization gap**

Today all services validate a single audience (`banking-demo`) against a shared HS256 key. This means a compromised agent holding a banker token can call `POST /api/transfers` directly, and the Banker Copilot approval ladder is pure decoration. 

Remediation: Introduce a second `banking-copilot` audience minted by user-service for harness-only authentication. This requires splitting the shared `banking-workload-identity` KSA to enable per-service Istio AuthorizationPolicy (currently impossible because KSA is shared). Identified by Turk during policy-engine spike. **Status: NOT STARTED; open question O7 to Danny for priority.**

**Finding 2: nginx configs lack `proxy_buffering off` — SSE trace streaming silently batches**

`infra/local/gateway.nginx.conf` and `ui-app.nginx.conf` have no `proxy_buffering off` on any `/api/` location. Without it, the entire SSE trace stream arrives as one lump when the run ends, silently defeating the live-harness illusion. The banker sees no events during the run, then the entire trace dumps at the end.

Remediation: Add `proxy_buffering off;` to all location blocks serving `/api/` paths carrying SSE streams. Identified by Linus during frontend-UX spike. **Status: BLOCKING; this is the single highest-risk non-frontend dependency in the epic and needs an owner now.**

---

## 2026-09-04T14:35:00Z — Banker Copilot Round 2: UI Requirements from Policy Engine Ruling

**Two requirements handed from this round's ruling work:**

### 1. Reason Code for Policy-Escalated Voids — `POLICY_RUNG_ESCALATED`

`approval.voided` event already exists (your existing §4.2 event kind). New requirement: when a signature is voided because the policy escalated (re-evaluated rung is higher than signed rung), surface a **specific reason code** (`POLICY_RUNG_ESCALATED`) that renders differently from other void causes.

**Banker-facing copy (critical for trust):** *"The approval policy changed while this was pending — this now requires supervisor co-approval (L1 → L2)."* Name the threshold transition and its environment variable. Do not render generic error. Someone who signed in good faith and finds it un-signed deserves the reason; generic failures train people to distrust the approval card, which this entire epic rests on.

**Mechanism:** Voided signature must explain itself, not fail generically. If you log `approval.voided` with terminalReason, that field must carry sufficient detail for the UI to render the right message — either the terminalReason itself must include both rungs, or it must be keyed to allow the UI to look up the transition.

### 2. Bulk Policy-Invalidation Events — No Bulk Re-Approve Affordance

When one policy edit invalidates N pending approvals:
- **DO:** Surface bulk `policy-invalidated` event digest to bankers (eager notification sweep, even if lazy void-at-execution is the correctness guarantee).
- **DO NOT:** Offer a "re-approve all 40" button.

Rationale: Bulk *re-proposal* is fine (they go back to pending, signers try again). Bulk *signing* reconstitutes blanket approval by the back door, at the moment of maximum approval fatigue (R3 — "just approve everything to clear the backlog") — the worst possible time for a single-click remediation. It's a general shape worth watching: a cleanup affordance that quietly undoes a control the system was built around.

**For Design:** `approval.voided` event carries policyVersion + rung transition (old and new). Trace persists both for #333 offline replay: can't tell "escalated correctly" from "mis-resolved" without both endpoints.

**Reference:** `docs/design/banker-copilot-policy-engine.md` §6.6 (operations), §7.2 (audit), §8.10 (/policy/impact endpoint).

**Verified Findings Appended to This Agent's History**

From Round 2 verified-findings pass (Coordinator's work):
- #334 — all 9 services can forge JWT tokens (shared symmetric key). Layer 2 blocked.
- #335 — event-processor silently drops 4 of 4 event types. Authority events inherit this gap.
- #336 — shared KSA for 11 pods blocks Layer 1 isolation.

---

---

## 2026-09-04: Banker Copilot Final Rulings — Canonical Vocabulary & Implementation

**CRITICAL UI UPDATE REQUIRED:**

Your `ApprovalState` TypeScript union previously carried `'expired'` and `'void'` states — **both now deleted by ratified rulings.** These states were removed from the specification, but the propagation to your type definition failed silently. This is the kind of decision-propagation failure that contract tests exist to catch.

**Before any UI implementation, re-read the approval lifecycle section in `docs/epics/banker-copilot.md` §5.1.**

The lifecycle is now: `proposed → pending → signed → executed`, with `denied` as the **single terminal rejection state**, differentiated by a mandatory closed four-value `terminalReason` enum:
- `HUMAN_DENIED`
- `POLICY_RUNG_ESCALATED`
- `TTL_EXPIRED`
- `PAYLOAD_SUPERSEDED`

**All four reasons now share `status = "denied"`.** Branching on `status` alone is a bug. The four must be **visually distinct on every UI surface** — especially the case where a banker's signature was voided by a policy change. That banker did nothing wrong; the ground moved. Copy must name the cause and link the replacement proposal via `supersededByApprovalId`.

**Canonical Vocabulary (Use These Names in All UI Code):**

| Concept | Canonical | Notes |
|---------|-----------|-------|
| Core entity | `approval` | Never `proposal` (noun). Use `proposed` (state) and `propose` (verb) only. |
| Requester identity | `requesterId` | Never `actorId`. |
| Supersede link | `supersededByApprovalId` | Holds an id; points to an approval. |
| Terminal reasons | `PAYLOAD_SUPERSEDED`, `HUMAN_DENIED`, `POLICY_RUNG_ESCALATED`, `TTL_EXPIRED` | Closed enum, all four required branches in UI. |
| Banker's conversation | `session` | One SSE stream. Multiple `run`s per session. UI watches sessions, not turns. |
| One cycle (intent→plan→tools) | `run` | Every envelope carries `runId`. |

**Requirement: `payloadHash` Display (Q2 Ruling)**

The `payloadHash` is PERMANENT and mandatory on every approval card:
- List views
- Detail views  
- Sign response confirmations
- SSE events

Server provides `payloadHashShort` for safe truncation. **Most legible security property in the system.** When re-sign is requested after a policy escalation, the changed hash next to the changed number *explains* the request rather than appearing arbitrary.

**Requirement: Denial Reason Validation (Q3 Ruling)**

When a banker denies a proposal with `HUMAN_DENIED`, they must provide a reason ≥20 characters, validated server-side (via `authority-service`). UI mirrors for responsiveness but never for enforcement (API always returns 400 on invalid input).

Degenerate inputs are rejected: `"        "` (20 spaces), `"aaaaaaaaaaaaaaaaaaaa"` (repeated char). The rule is trimmed + length + distinctness + letter count, stopping lazy input but not determined garbage.

**Requirement: Step-up Auth at L2 (Q4 Ruling)**

**The banker's own second signature never suffices at L2, MFA included.** SoD means different people, not different proofs. A fully-authenticated banker making a bad or self-interested decision is not solved by re-proving their identity. The distinction:

| Control | Defends Against | Question |
|---------|-----------------|----------|
| MFA/step-up | Stolen session/credential | Who is signing? |
| Separation of Duties | Legitimate user making bad decision | How many people reviewed? |

Enforce structurally: if the system shows "MFA required to co-sign as yourself" it becomes L1 wearing a hat, and every threshold above L1 becomes theatre. This is not a recommendation; it is a structural requirement — no policy verb can empty the "different signer" constraint.

---


### 2026-09-04 — Feature flag scaffolding for surface coexistence (#332 Phase 5 revision)

**Context.** Brian overruled Phase 5: admin tabs are not retired, they coexist behind a flag so
the same task can be run on both surfaces and compared. I built the flag system and the
comparison instrumentation in `src/ui-app/` ahead of Phase 2, and updated
`docs/design/banker-copilot-ui.md` (§1.3 rewritten, new §10 and §11).

**CRA inlines `process.env.REACT_APP_*` as literal text.** This is the trap of the day.
`process.env[someVariable]` is not a lookup at runtime — webpack's DefinePlugin does *textual*
substitution at build time, so a computed key silently resolves to `undefined` in the production
bundle while working perfectly in `npm start`. Any dynamic env-var registry in CRA needs a
hardcoded static-access map. I wrote the workaround with a comment explaining why, because the
code looks needlessly verbose without it and someone will "clean it up".

**MUI v9 prop breaks that `tsc --noEmit` does NOT catch.** Two of them, both only surfaced by
`craco build`: `<Switch inputProps={{...}} />` must become `slotProps={{ input: {...} }}`, and
`<Stack alignItems="center">` is no longer a valid direct prop (goes in `sx`). Lesson: a clean
standalone typecheck is not sufficient validation for MUI-heavy changes in this repo. Always run
the actual build.

**Runtime config for a static SPA: a `.js` file, not a `.json` file.** ui-app is a CRA build
served by nginx with no runtime env vars, and the docker-compose service has no `environment:`
block at all — so the only honest runtime vector is a mounted file. A fetched `config.json` is
async and guarantees a flash of the wrong surface on every boot; a synchronous `<script>` in
`<head>` before the bundle resolves flags before React mounts. Same file mounts identically under
docker-compose (volume) and kustomize (ConfigMap + `subPath`), which preserves the repo's
dual-mode convention.

**URL overrides belong in sessionStorage, not localStorage.** A link someone sends you must not
permanently reconfigure your browser. Corollary I nearly missed: when the user flips the in-app
toggle, you must *clear the sessionStorage entry first*, otherwise the link-supplied value keeps
outranking the switch they just flipped and the toggle looks broken.

**Encode metric directionality at the point of definition.** Epic §9 risk 1 says a falling
time-to-sign is a defect, not adoption — it is what approval fatigue looks like in a chart. That
inverts how anyone normally reads a latency metric, so I added a `MetricDirection` including
`lowerIsSuspicious` to the metric definitions themselves and asserted the directions in tests.
If that knowledge lives only in a chart config or a slide, someone eventually celebrates the wrong
number and produces a confident false conclusion. Generalises: whenever a metric's obvious reading
is wrong, the correction has to travel with the metric.

**Pre-register before you can rig it.** Both the metric set and the shared task set are fixed in
code *before the harness exists* — the one moment I am honestly incapable of choosing measures
that flatter the thing I designed. I also deliberately included a task (`review-flagged-txn`) that
is Classic Admin's best case, so the comparison can actually be lost. And
`exportComparisonData()` embeds `interpretationWarnings` in the payload, because a number in a
spreadsheet outlives its footnote.

**Say "not a security control" three times or it will be misread once.** Module comment, UI copy,
and design doc. The refusal screen for a disabled surface is deliberately loud and offers a
one-click re-enable — an authorisation failure would never hand you a button that fixes it, and
that asymmetry is what stops anyone leaving the screen thinking the flag protected something.

**Vocabulary drift is a real cost.** Reconciling the design doc to the ratified lifecycle
(`proposed → pending → signed → executed`, `denied` + `terminalReason`, no `expired`, no `void`)
touched ten places including an event name I had invented (`approval.voided` → `approval.terminal`)
and a demo-script beat. Also absorbed the `cosignerId` deletion: the UI must say "awaiting a
supervisor", never "assigned to you", because naming a co-signer at proposal time lets a banker
pick their own reviewer — the exact self-dealing L2 exists to prevent. Presentation can
reintroduce a field the data model deliberately omits; watch for that.
