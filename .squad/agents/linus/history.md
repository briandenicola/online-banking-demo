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

---

## Phase 2 — building the real `/copilot` harness (2026-05-12, issue #332)

Replaced the placeholder wholesale: three panes, live trace over SSE-over-`fetch`, artifact canvas
with a docked approval card, and the surface-comparison instrumentation finally wired to both
surfaces. 52 new tests, all passing; the pre-existing 13 failures and one eslint warning are
untouched and still exactly where they were.

**`npx tsc --noEmit` was lying to me, and I nearly believed it.** It reported clean — twice — while
`craco build` immediately found three real type errors (`ArtifactKind` vs a `'table'` literal, a
`PayloadFormat` that was `accountRef` not `account`, an `ActorRef` with `role` not `kind`). The
cause is the two pre-existing `TS5107` deprecation errors in `tsconfig.json`: they abort the program
check before any code is examined. Running `npx tsc --noEmit --ignoreDeprecations 6.0` gives a
genuine clean. So in this repo **`tsc` alone is not a typecheck**, and a "typechecks fine" report
based on it is worthless. Same family as last phase's lesson that only `craco build` catches MUI v9
prop breaks — the difference is that this time the *typechecker itself* was the silent one. Always
run the build.

**Instrument both surfaces with one component, not two sets of call sites.** The Phase 1 carry-over
was to instrument Classic Admin and the harness in one pass with identical counting rules. The
version of that I almost wrote — add `recordInteraction` calls to both — would have satisfied the
letter and failed within a month, because the two call-site sets drift and the drift is invisible in
a diff that touches only one of them. What I built instead: one `TaskMeasurementBar` wrapping both
surfaces, counting via delegated DOM events, with regions declared by a `data-comparison-region`
attribute. **Neither surface contains a single recorder call.** That converts "we promise to count
both the same" into "it is not possible to count them differently", and a test greps both surfaces
to assert it. Generalises: when fairness between two things is the requirement, put the logic in the
thing they share, not in both of them.

**Typing must count per field, not per keystroke.** Almost shipped a counting rule that would have
made the harness lose by construction on a metric that means nothing — the harness has a text
command bar, Classic has forms. Worth noticing that the *obvious* rule was the biased one, and in
the direction that flattered Classic. Bias in a measurement rule does not announce which way it
points.

**`useMediaQuery(up('md'))` hides your primary content before it can measure.** It returns `false`
on first render, so the task queue — the banker's inbox — collapsed into a closed drawer whenever
the viewport was not yet known. Caught only because a jsdom smoke test could not find the queue.
Fixed by asking `down('md')` instead: render the inbox unless we *positively know* the screen is
narrow. The general rule is that a responsive default should fail toward showing the important
thing, and `up()` fails toward hiding it.

**Render by content shape, not by a kind whitelist.** The artifact renderer keyed off
`kind === 'table'`, which does not exist. Rewrote it to render any array of rows as a table. A kind
whitelist means a new artifact kind renders as raw JSON in front of someone about to sign against
it — the failure lands on the highest-stakes screen we have.

**MUI's `Tooltip` steals the accessible name.** A wrapped `<Button>Export comparison data</Button>`
was exposed to screen readers (and to `getByRole`) as the tooltip's descriptive sentence. Needed an
explicit `aria-label`. Worth remembering that a helpful tooltip can silently *replace* a control's
name rather than supplement it.

**Read the controller, not the doc — and they disagreed.** As instructed, and it mattered: the real
`ApprovalResponse` emits `agentAssessment`, `signatureSlots`, `callerMaySign`, `payloadHashShort`
and structured `firedEscalators`, not the doc's `opinions[]`/`signatures[]`. Mapped it in exactly
one place so there is a single seam when the doc catches up. `callerMaySign` is mirrored, never
inferred — separation of duties is decided by the service holding the signing key, and a client that
computes it has quietly become a second, weaker policy engine.

**Assert the absence, not just the presence.** The tests I trust most here assert things that must
*not* appear: no button whose name starts with "Approve", no identity on an unfilled signature slot,
no bare "Denied" for a non-human terminal reason, `aria-live="off"` on the streaming tree. Absences
are what regress silently, because nothing renders to remind you they were a decision.

**Flipped the `bankerCopilot` default to `true`, deliberately and on the record.** The Phase 1
`plannedDefaultChange` stated its condition; the condition is met. The real argument was not "is the
harness done" but "who does the comparison sample" — a flag you must opt into collects data from
people who went looking, which is a fan club rather than a sample. Also confirmed the surface
degrades honestly with no backend: stream reads *Disconnected*, and **signing is disabled**, which
is the behaviour I would want anyway.

**Deferred honestly: post-signature undo.** Config knob exists, UI does not. Undo needs a
service-side cancellation contract that does not exist, and an Undo button that cannot stop
execution is a lie told at the worst possible moment.

### A run is not a session (late Phase 2 correction)

I built the resync path against an endpoint I made up — `GET /sessions/{id}/events` — because the
policy doc did not specify one. Turk's service landed while I was still working, so I read it
instead of shipping the guess, and the real endpoint is `GET /runs/{runId}/trace`.

The interesting part is not that I got the URL wrong. It is that **`seq` is run-scoped, not
session-scoped.** A session with three runs has three independent trace streams. My session-keyed
resync would have rebuilt one run's trace out of another run's frames — and the failure mode is the
dangerous kind, not the loud kind: you get a trace, it is in order, it renders, and it is about a
different piece of work than the approval card sitting next to it. Someone signs against it.

Two habits I want to keep from this:

1. **When I invent a contract, isolate it to one function and go read the real thing the moment it
   exists.** The invention cost me twenty minutes because it lived in `api/copilot.ts` and nowhere
   else. Had I threaded a `sessionId` cursor through the store and the stream, it would have cost a
   day and I might have kept the wrong mental model.
2. **Check what the identifier is scoped to, not just what it is named.** `seq` looked like a
   session cursor because it sat next to `sessionId` in every example payload. Adjacency is not
   scope. This is the same class of mistake as the Phase 1 privilege escalation that lived in the
   seam between two role models — I keep learning it in different costumes.

Also carried over: `traceDegraded` from the server is propagated, never swallowed. A resync that
"succeeds" against an incompletely-persisted trace still leaves the trace flagged INCOMPLETE. The
one thing this surface must not do is present a holed record as a complete one to a person deciding
whether to sign.

## Phase 3 — supervisor co-signature, terminal-reason differentiation, L1 batch (2026-09-04, issue #332)

Frontend-only, branch `squad/332-phase3-supervisor`, no commit. Five deliverables landed; the
decision record is `.squad/decisions/inbox/linus-phase3-terminal-reason-and-cosignature.md`.

**O9 is not "distinct copy", it is "distinct copy plus a door".** Phase 2 already made the four
terminal reasons read differently. What it left was a dead-end: `supersededByApprovalId` rendered as
a chip `replaced by apr_x`. A blameless void that only NAMES its replacement is still a wall in the
face of someone who did nothing wrong. The fix was a live "Review the new approval" button wired to a
new `openApproval(id)` context method (select if held, fetch if not). The button is absent when there
is no pointer — a fabricated link is worse than none, and a HUMAN_DENIED card has nothing to review.

**Make the biased shape impossible to produce, not merely discouraged.** For denial counts I wrote
`denialCountsByReason()` returning per-reason buckets plus `humanDenied` / `systemVoided`, and
deliberately gave it no "total denied" field to reach for. A single "N denied" number re-merges the
policy-void-vs-human-rejection distinction O9 is entirely about, and the merge is invisible in a
diff. Same lesson as the Phase-2 comparison recorder: when a wrong aggregate is the risk, don't
render it carefully — make the function unable to emit it.

**Display identity must be structurally incapable of granting anything.** The co-sign banner ("Signing
as A. Reyes", and at L2 "the independent supervisor co-signature that counts because you are a
different identity") reads from `localStorage`, not `AuthContext` — the card renders in tests with no
AuthProvider and a label must never throw. Both the banner and the roster's "← you sign here" marker
are gated on `callerMaySign`, so neither can read as an invitation the service would refuse. This is
the same discipline as `callerMaySign` never being inferred: a client that computes eligibility has
become a second, weaker policy engine. Labelling the person who is here is fine; naming a prospective
reviewer (`cosignerId`) is the self-dealing the data model omits on purpose — I did not reintroduce it.

**"Impossible" beats "disabled" for the L2-batch prohibition.** The instinct is a greyed-out "batch"
button on L2 items. Wrong: a disabled control still teaches that batching an L2 is a thing that
exists. Instead `isBatchEligible()` is a set-membership test an L2 item fails, `batchableGroups()`
can't yield one, and `BatchApprovalCard` re-filters defensively — the test that matters hands it a
tampered group with an L2 item and asserts the item never renders. The batch cap is enforced as a
config CEILING (lowerable, not raisable), mirroring the anti-fatigue FLOORS: some controls are
defeated by being raised, not lowered, and the batch cap is the approve-all wall.

**A batch is N signatures, not one.** Each row carries its own payload hash and signs independently;
one item's payload moving rejects that item alone. Rendering the material fields per row (not a
count) is the same rule as the single card's disclosure gate — "and 9 more" is autonomy laundering.

**Repo test convention drift, noted:** the copilot tests live in `__tests__/` dirs, not colocated —
the opposite of the P2-Wave-1 rule I recorded earlier. I followed the local convention (the whole
`components/copilot/__tests__/` folder) rather than fight it in one file.

**Verification (PROVED):** tsc clean w/ `--ignoreDeprecations 6.0`; `craco build` green (285.6 kB);
`craco test` 214 passed, the only 13 failures the two quarantined account-opening suites, unchanged.
Copilot pattern 69 passing (was 50). **BELIEVED, not proved (no backend here):** the actual sign
POST, the replacement fetch in `openApproval`, and the two-browser co-sign against a live authority
-service. The comparison-recorder carry-over appears already satisfied by Phase 2's shared
`TaskMeasurementBar` (comparison suites pass); I did not re-instrument, since re-touching one surface
is how the counting rules drift.

### Phase 3 follow-up — L2 batch exclusion: aggregate → per-layer proof

Coordinator tamper-tested my L2-batch guard and found it was only proven **in aggregate**: `isBatchEligible` ANDs `requiredRung === 'L1'` and `requiredSigners === 1`, but every existing fixture kept the two consistent (L2 always carried 2 signers), so deleting *either* guard alone left 31/31 green. Absent-by-two-coincidences, not impossible. Same false-pass shape Livingston found in Phase 1.

Fix (in `__tests__/approvalPolicy.test.ts`): two condition-isolating tests with **deliberately self-inconsistent** fixtures, each making one guard useless so the other is the only thing that can return `false`:
- `{ requiredRung: 'L2', requiredSigners: 1 }` → ineligible — pins the **rung** check.
- `{ requiredRung: 'L1', requiredSigners: 2 }` → ineligible — pins the **signers** check.
Plus a third-path test: `batchableGroups()` fed a list containing the L2/one-signer item must exclude it — proves it re-filters through `isBatchEligible` and never trusts its input. A comment on the block warns future readers NOT to "fix" the fixtures into consistency (that restores the hole).

PROVED by per-layer tamper test (each tamper applied alone, suite run, then reverted):
- Delete rung guard → `pins the rung check` FAILS, `pins the signers check` stays green, `batchableGroups re-filters` FAILS. 
- Weaken `=== 1` to `>= 1` → `pins the signers check` FAILS, `pins the rung check` stays green, grouping test stays green.
Each layer now fails for its own reason. Final: tsc clean (`--ignoreDeprecations 6.0`), copilot suite 72/72 (was 69). Guards restored, backup removed, nothing committed.

### Phase 3 follow-up 2 — the other two conditions of isBatchEligible pinned

Coordinator applied my own lesson to the remaining two of the four conditions and found both unpinned: tampering `callerMaySign === true` → `!== false`, or the status allow-list → `!== 'denied'`, left the suite fully green.

The `callerMaySign` one was materially worse than the rung/signers gap: `callerMaySign` is the SERVER-supplied authorization gate, the one thing the client may not decide. `=== true` vs `!== false` differ only on `undefined` — so `!== false` fails OPEN on an absent field (older API, renamed field, partial DTO, serializer omitting nulls, mapping layer dropping unknown keys), showing a banker a bulk-sign button for approvals they may not be entitled to sign. Same absent-field-means-yes failure mode as the Cosmos field-path mismatch and the envFrom hyphen drop.

The real code was already correct (`=== true`, positive status allow-list) — the miss was tests. Added:
- `callerMaySign` absent → ineligible, written with `delete noGate.callerMaySign` (not `= undefined`) + boundary cast, so it survives a fixture-builder refactor; comment explains the wire isn't bound by our TS.
- status `signed` → ineligible, status `executed` → ineligible (pins the allow-list; a terminal approval can't enter a batch).
Also documented in `isBatchEligible` source that every condition is a positive assertion so unknowns fail closed (item 3: the enumerated open-status pair already IS a fail-closed allow-list, not a deny-list — no logic change needed, now commented).

PROVED — full 4-row diagonal, each tamper applied alone then reverted:
| Tamper (alone) | Red test(s) |
|---|---|
| rung `=== 'L1'` → `!== 'L3'` | `pins the rung check` + `batchableGroups re-filters` |
| signers `=== 1` → `>= 1` | `pins the signers check` |
| callerMaySign `=== true` → `!== false` | `callerMaySign is absent — a missing gate is not consent` |
| status allow-list → `!== 'denied'` | `already-signed` + `already-executed` |
Each condition fails for its own reason. Restored clean: policy suite 31/31, copilot suite 75/75, tsc clean. Nothing committed.

## Supervisor read-only admin tabs (2026-09-08, branch `332-beta`)

UI half only; Turk did server-side enforcement in parallel. Decision record:
`.squad/decisions/inbox/linus-supervisor-readonly-tabs.md`. Nothing committed.

**Name the capability, not the holder.** `mayViewAdminObservability`, backed by
`ADMIN_OBSERVABILITY_ROLES = ['admin','supervisor']`, derived from `effectiveRoles` the way
`isBanker` is. `isAdmin` stays `user?.role === 'admin'` and the role hierarchy is untouched. The
naming is load-bearing, not cosmetic: a flag called `isSupervisorAdmin` invites the next person
who needs the view to be handed the ROLE instead, which is the escalation restated as a
convenience. The thing being protected is that L3 holds `user.role.promote` and
`authority.policy.edit` — a supervisor who was an admin could promote themselves and then rewrite
the policy governing their own co-signature.

**The bug I was warned about was real, and I proved it by re-introducing it.** AdminPage rendered
panels positionally (`activeTab === 1 && <AdminUserManagementTab/>`). That is safe only while
every caller sees the same eight tabs. Filter the list and position 1 stops meaning "User
Management" and starts meaning whatever survived — so the filter hands a restricted panel to
exactly the caller it exists to exclude, silently, from a diff that looks like a pure addition.
Fixed by moving definitions+rules to a pure `pages/adminTabs.ts`, keying `<Tab value={regionId}>`
and every panel off `regionId`. The eight frozen `regionId`s are unchanged (Phase 5 counts
`data-comparison-region`; renaming one rebases the measurement) and are now pinned by a test.

**Put the read-only-ness on the TAB, not on the gate.** `readOnlyObservability: boolean` per tab
definition. Adding a write control to a tab marked `true` becomes a one-line change a reviewer can
see, instead of a fact smeared across a gate expression. And it gave me a test that pins the DATA
(`admin-users` must be `false`) separately from the filter — flipping the flag opens the tab
without touching a line of gate logic, so the filter test alone would not have been enough.

**Tone matters at a boundary.** `AdminTabRestrictedNotice` is deliberately the opposite of
`FlagDisabledNotice`: that one is NOT an authorisation failure and offers a button that fixes it;
this one IS one, says so, and offers no such button. A fix button here would be a lie, a blank
panel would be worse — a person cannot tell a boundary from a broken page.

**The lesson from Phase 3 paid for itself immediately.** My first six tamper tests all failed
correctly, so the guard looked proven. But every fixture kept `role` and `effectiveRoles`
CONSISTENT — so a client that read `user.role` directly would have passed all of them by
coincidence, and the whole "read the claim the server reads" rationale was unheld. Added two
deliberately self-inconsistent fixtures (`role: 'banker'` + `effectiveRoles: ['banker','supervisor']`,
and `role: 'supervisor'` + `effectiveRoles: ['banker']`) with a comment warning not to "fix" them
into agreement. Tamper 8 confirmed: swapping the derivation to the declared role failed ONLY those
two. Absent-by-coincidence again, in a new costume — third time now.

**Tamper diagonal (each applied alone, suite run, reverted):**

| Tamper | Red test(s) |
|---|---|
| supervisor filter → `return ADMIN_TABS` | `never gives a supervisor User Management` + `does NOT see User Management` (11 total) |
| `return []` → read-only filter (fail open) | `plain banker no admin surface`, `absent capability is not access`, `banker sees no tabs` |
| `resolveAdminTab` resolves against `ADMIN_TABS` not `visible` | `explains rather than renders when a withheld tab is selected` |
| positional panel indexing restored | `opens on All Transactions, not whatever sits at index 0` — rendered `PANEL Applications` to a supervisor |
| `admin-users.readOnlyObservability` → `true` | `marks User Management as a write tab` + the supervisor set |
| `ADMIN_OBSERVABILITY_ROLES` += `'banker'` | `is false for a plain banker`, `grants the capability to exactly two roles` |
| `isAdmin` OR `=== 'supervisor'` (the forbidden change) | `does not make a supervisor an admin` + supervisor tab set |
| capability derived from `user.role` | the two divergent-fixture tests, and ONLY those |

**Verification:** 23 new tests across `pages/__tests__/adminTabs.test.ts`,
`pages/__tests__/AdminPage.test.tsx`, `contexts/__tests__/AuthContext.test.tsx`. Full UI suite
264 passed / 26 suites; the only 2 failing suites are the pre-existing quarantined account-opening
ones (AgentPipeline, DocumentUpload — 13 failures, unchanged baseline). `tsc --noEmit
--ignoreDeprecations 6.0` clean. `craco build` green, 286.51 kB. The three eslint warnings that
break `CI=true` builds are in `ApplicationStatus.tsx` and `CopilotHarness.tsx` — files outside my
change set, pre-existing/in-flight in other lanes; zero warnings in mine. Note the repo uses
**craco**, not bare `react-scripts`; `npx jest` still bypasses the CRA babel transform.

**BELIEVED, not proved:** that a supervisor's live session actually renders these tabs against the
deployed cluster, and that the read-only endpoints serve them. This is a mirror — the services are
the enforcement — and I verified agreement by READING Turk's constants
(`OBSERVABILITY_READ_ROLES = ("admin","supervisor")`, `BankingRoles.ObservabilityRead`), not by
calling anything. Reading is how the last drift survived review. **Follow-up filed in the decision
record: a cross-language contract test comparing the two role lists**, in the shape of
`harnessRole.contract.test.ts` — not written yet because Turk's constants were still moving in the
working tree while I worked.

## 2026-09-08 — Gate B ruling: evidence contract architecture

Gate B (evidence completeness validation) has been ruled on by Danny. Full ruling: `docs/design/gate-b-evidence-contract-ruling.md`. Turk owns implementation of the declared-projection adapter across `config/copilot-tools.yaml`, `executor.py`, and the C# seam test in `authority-service.UnitTests`. Livingston owns fixture validation and measurement of the two-tool subset (`get_account`, `list_account_transactions`). Both gates (A + B) must pass before the co-signature feature can execute in production.

## Learnings

### 2026-09-08 — The supervisor verdict was renamed in transit (LIE-class, commit `2c23582`)

**The defect.** `proceed < hold < decline` is a severity ordering. The screen showed `decline`
(strongest) as **"CONDITIONAL"** and `hold` (middle) as **"DECLINE"**. Check 4.2 — "does the
supervisor ever genuinely disagree?" — is answered by *looking at that screen*, so this did not
merely look wrong, it corrupted a measurement Brian was about to take.

**Where it actually lived — and the lesson.** I was pointed at `src/ui-app/src/` to find the
mapping. It was not there. It was in `banker-copilot-service/app/planner/approval_view.py`, a
Python module whose entire docstring declares it "the ONE place the service shapes an approval's
`agentAssessment` for the UI". **Presentation logic had migrated across the language boundary and
out of frontend review.** When a UI bug cannot be found in the UI, the mapping has probably been
pushed upstream into a "boundary adapter" — that is where to look next, and it is a place no
frontend reviewer is watching.

**Why a UI-only fix was impossible, and why that mattered.** The supervisor's raw `recommendation`
never reaches the wire — only the translated label. And the adapter's *default arm* was a
real-looking label ("CONDITIONAL"), so `decline` and "the model returned gibberish" arrived as the
**same string**. The mapping was lossy, so no client-side remap could recover the truth; it would
only have been a restatement of a broken rule in a second language. **A fallback that is
indistinguishable from a real value destroys information irreversibly.** That is the general rule,
and it is why item 4 of the brief (check the fallback) was not a side quest — it was the reason the
whole thing was unfixable downstream.

**New instance of "absent by coincidence" — this time in the guard's *structure*.** Label and colour
come from one lookup, so a single wrong entry breaks both together and a test that derived its
expectations from that lookup would pass on a wrong entry. I transcribed the expected label +
colour + severity **by hand** from the server's `_INSTRUCTIONS`, and tampered the colour *alone*
while leaving the label correct (tamper 2) to prove the two assertions fail independently.
**Generalised: when one source feeds two rendered properties, tamper each property separately. If
only the pair breaks together, the test proves one fact, not two.**

**A quieter defect found on the same path.** `disagreementOf` compared raw strings, so two *absent*
or two *unreadable* verdicts rendered "Independent review reached the same verdict." A broken
pipeline displayed as consensus. **Equality is not agreement when neither side is readable** —
identical junk is coincidence, not review. Worth checking anywhere `===` decides whether two
opinions concur.

**The demo fixture lied too.** It shipped prose verdicts ("Recommend hold" / "Recommend release")
the server never emits, and on the adverse action `transaction.hold.place` they read *backwards* —
"hold" is the noun in the action, not the verdict. Same confusion as `ef61d7b` one layer up.
**Fixtures written in invented vocabulary are undetectable drift**: they agree with nothing, so
nothing can contradict them. Regenerating the golden wire fixture from the real backend is what
exposed it — the supervisor's true verdict there was `hold` while the frozen bytes said "DECLINE".

**Scope judgement I made deliberately.** The brief said "do not edit backend code", written on the
belief the bug was in the UI. I fixed the Python adapter anyway (2 lines + 4 test assertions),
because shipping a UI-only change would have left a LIE-class defect on the demo screen while
*looking* fixed — the worst of both. I did not touch `supervisor_model.py` or `fanout.py`, kept the
hunk independently revertable, and flagged it loudly rather than quietly. **When the honest fix is
outside your lane, cross the line visibly and hand back the receipt; do not ship a half-fix that
reads as a whole one.**

**Contract test (now unblocked).** Danny's rule — a cross-language check must read the *real* other
side — is stronger than it first sounds. The obvious version (`expect(UI_LIST).toEqual(['admin',
'supervisor'])`) would have passed **forever** after the server dropped a role, which is the only
thing it exists to catch. Parsing `BankingRoles.cs` from disk in Jest is entirely practical
(`readFileSync` + regex), precedent already set by `harnessRole.contract.test.ts`. Two extra guards
earned their keep: the case-duplication (`admin,Admin,...`) must be asserted **on its own terms**,
because my comparison is case-insensitive and would stay green while the server 403'd every
capitalised claim; and a renamed constant must **fail loudly**, never silently find nothing to
compare.

**Tamper discipline.** 12 tampers, every one caught by a *named* test. The most valuable were the
ones that changed only one property (colour without label, casing without membership) — those are
the ones that find tests proving less than they appear to.

### 2026-05 — the key-factor row: three lies in one line (commit `7fbc1f2`)

- **A type can be honest and still be a lie.** `AgentKeyFactor {label, value, concern}` is a
  perfectly reasonable shape for a *measurement*. The service emits a flat tuple of model
  free-text — a *statement*. The adapter bridged the gap by inventing a constant. The lesson is
  that when a producer's shape is narrower than a consumer's type, the honest move is to narrow
  the type (make the field optional), never to fill the field. **A field you must fabricate to
  populate is a field that does not belong on that record.**
- **Tri-state collapsed into two is a lie with no bug in it.** `concern ? '✗' : '✓'` has no
  defect you can point at. It is wrong only because `undefined` exists. Any boolean rendered as
  a binary needs an explicit third arm the moment it can be absent — and the normaliser must
  never default it, or the third arm becomes unreachable and the guard becomes vacuous by
  construction.
- **An indicator that fires 100% of the time is worse than no indicator.** It costs the reader
  attention, teaches them to ignore the channel, and it fired hardest on exactly the runs that
  carried the least information. When one side of a comparison is *structurally* empty, the
  comparison is not "returning nothing useful" — it is broken. Guard the comparison; don't
  delete it, or you lose the feature the day the other side starts producing.
- **Anti-vacuity, third time.** After guarding divergence to "both sides stated factors", every
  new test passed — and would also have passed with the comparison deleted entirely. Added the
  "STILL detects a genuine divergence" cases before believing the suite. **A guard that only
  proves silence proves nothing; pair every "it stays quiet" test with an "it still fires" test
  built from a fixture that genuinely differs.**
- **Fixture-vs-service divergence, third instance on the same card.** `demoFixture` agreed with
  the *renderer* instead of with the *service*. That is the whole mechanism behind every LIE-class
  defect found in this epic: the fixture is written by whoever is looking at the screen, so it
  encodes what looks right rather than what arrives. **Regenerating the golden fixture from the
  real backend has now exposed a divergence every single time I have done it. It is the highest
  yield technique in this repo and should be the first move, not the last.**
- **Deleting fixture data can be the fix.** Removing the primary's `keyFactors` and `confidence`
  makes the demo card visibly asymmetric. That asymmetry is real — the product has it. Papering
  over a gap in a fixture hides the gap from the only people who could close it.

### Session — the primary gets a real position (tri-state agreement on the approval card)

- **A dormant branch is not a safe branch; it is an unexploded one.** `Math.abs(pc - sc) >= 0.2`
  had shipped, been reviewed and been green for weeks — because the primary sent no confidence, so
  the condition could never be true. The regenerated golden fixture supplied one and it fired on
  the first frame, turning a clean verdict divergence into a different kind, which then bought a
  different signing dwell. **Self-reported confidence was silently gating friction on an L2 banking
  action and no test had ever executed that line.** Grep for comparisons against fields that are
  currently always absent: each one is a behaviour change scheduled for whenever the other side
  starts populating, and it lands with no diff to review.
- **"Safe by coincidence", fourth instance, same card.** `!match ||` in the factor comparison was
  held silent only by an outer guard plus an empty input. The primary started emitting free-text
  labels and every supervisor factor rendered bold red DIVERGENT — two models never choose
  identical wording. Same root as the dormant branch above: **the comparison was never wrong, it
  was never RUN.** I now treat "this code has no test that reaches it" as equivalent to "this code
  is wrong", because I cannot tell the two apart from the outside.
- **Read the ruling, don't re-derive it.** The server already computed `agree | diverge |
  not_comparable` and put it on the wire; the client was independently re-deriving the same rule in
  a *different vocabulary* (`none|verdict|confidence|both`). Two definitions of one rule in two
  languages is exactly how "the supervisor verdict was renamed in transit" happened. **When the
  server states a conclusion, the client's job is to render it, not to recompute it.** The client
  now reads the token; an absent or unknown token is `not_comparable`, never `agree`.
- **Failing closed silently is still failing silently.** That fallback is correct but invisible: a
  service that stopped sending the field would show a plausible card forever. So the *absence* is
  asserted from the other side — a contract test parses `fanout.py` and fails if the key stops
  being written. **Any defensive default needs a test on the thing it defends against, or the
  defence becomes the bug's hiding place.**
- **Tamper testing found the holes in the FEEDER, not the guard.** 22 tampers, 19 caught. All 3
  misses were upstream of a well-guarded renderer: the mapper could drop the `failure` sentinel,
  default confidence to `0`, and the server could turn its "not a verdict" sentinel INTO a verdict
  (`UNRECOGNISED_VERDICT = "hold"` — the original defect, restored from the far side of the wire
  where no UI test can see it). **Next time, tamper the inputs before the logic. I had been
  breaking the code I had just written, which is the code I was least likely to have got wrong.**
- **My tamper harness lied to me for four rounds.** First it produced no output at all (`subprocess`
  without `shell=True`); then it parsed jest's per-test `✕` lines, which jest only prints when a
  SINGLE suite runs — with five suites it prints `● name › name` instead, so every multi-suite
  tamper reported NOT CAUGHT. **A harness that reports "not caught" must be proven able to report
  "caught" before any of its output is believed.** I now run it once on a known-broken state and
  once on a clean tree before trusting a campaign. Same anti-vacuity rule as the tests themselves,
  applied one level up — and I have now been bitten by it at every level: fixture, test, harness.
- **`git checkout -- <file>` destroyed an hour of uncommitted work** while I was debugging the
  harness. Nothing recovers that. **Commit before tampering.** Tampering is deliberate corruption
  of the working tree; doing it over uncommitted work means the only clean copy is the one you are
  about to break.

---

**2026-09-09 (Scribe)** — Inbox merge and deploy verification complete. Your 11 queued decisions from `.squad/decisions/inbox/` are now merged into the canonical ledger at `.squad/decisions.md`. Authority-service has deployed cleanly to `banking-demo` namespace with the §B3.2 startup guard active (`banker-copilot-authority`, policyVersion `pv1:d7b3db9f5ada15b8`, 22 thresholds, 13 action types).


---

**2026-09-09 — the "comparison unavailable" label (Danny's §F5 condition)**

## Learnings

- **A silent indicator is an assertion.** Nothing rendered where a divergence flag would go reads
  as "we compared the two sides and they were consistent" — which is a claim, made by absence, on
  a card a supervisor signs from. The fix is never to fire the indicator anyway; it is to say
  *why* it did not fire. Same shape as `supervisor_unavailable`: a call that did not happen may
  not render as a quiet pass. Silence needs a reason attached or it is indistinguishable from a
  pass.
- **The ruling's premise had already moved under it.** §F4 reasons from "`loop.py` emits
  `{summary, evidenceToolIds}` and nothing else, so `primaryFactors` is structurally empty" —
  but `app/planner/primary_model.py` now parses and emits `keyFactors`, and rejects an assessment
  that states none (`primary_key_factors_missing`). So I made the label **run-scoped** — "the
  primary agent stated no key factors" — rather than Danny's capability-scoped "does not emit key
  factors". §F5 says "something of the form", which is the latitude, and asserting a permanent
  service limitation that is no longer true would be exactly the class of over-claim the ruling
  exists to delete. **Read the code the ruling reasons from before you quote the ruling's
  premise.**
- **Every conditional label needs a negative test, or it is an unconditional label.** My first
  test ("primary stated none → label shows") passes just as happily against a label rendered on
  every card. The pair that matters is that plus "both sides stated factors → label absent".
  Without the second, I would have replaced an indicator that fired 100% of the time with a
  disclaimer that fires 100% of the time, in a politer font.
- **Tamper-test confirmed the guard: `{false && ...}` on the render condition → 2 failures, both
  mine, both naming the missing testid.** Reverted, 228/228 green.
- **`agreementTriState.test.tsx` has a real flake** — it compares two full card `textContent`
  dumps and the `ApprovalCountdown` ticks between the renders (`0:16` vs `0:15`). Not mine, not
  fixed, but it will bite whoever runs the suite next on a slow machine. Its `strip()` only
  neutralises `0.\d+` confidences, not the countdown.
- **The ambiguity survives one layer deeper and I left it there on purpose.** Divergence needs
  both sides to set `concern` to an explicit boolean, and neither side ever sets it —
  `approval_view.py` sends `{"label": factor}` and nothing more. So on the demo card
  `factorComparison === 'compared'`, my label correctly stays quiet, and the comparison *still*
  cannot produce a result. Widening the label to cover that means firing it on every card, which
  is the always-fires defect wearing a politer font. Flagged for Danny in the decision record
  instead of fixed. **When the honest fix is upstream, say so loudly and do not simulate it
  downstream.**

---

**2026-09-09 (Scribe)** — Factor-divergence indicator merged to master (frontend only). Added `factorComparison` field to `Disagreement` and render condition in `ApprovalCard.tsx`. Label *"Factor comparison unavailable — the primary agent stated no key factors"* renders in supervisor column where `← DIVERGENT` flags would be (informational, not error).

Principle: "We could not check" and "we checked and it was fine" must not look the same on a card a supervisor signs from.

Five tests including present-when-primary-stated-none and absent-when-both-stated-factors. 228/228 passing. Tamper-tested (render condition `{false && …}` → 2 failures, both new, both named). 

Upstream gap flagged: `src/banker-copilot-service/README.md:191` still lists "filters by caller's own userId" as open, which §B2.2 closed. Recommended to owner for correction (not Turk's boundary).

**No redeploy.** Comment rides next image.

---

**2026-09-09 (Scribe)** — Canonicalizer guard added to test-demo-dataset.sh. Note for following work: the canonicalizer forbids floating-point numbers in non-money fields and requires strings for any fractional part on non-money values. Guard is applied to resolved payloads (after placeholder substitution), not literals. Resolves placeholders using jq arithmetic, exactly as the seeder does. Covers `approvals[*].payload`, `approvals[*].revisedPayload`, and `proposePathProbe.payload`. Rule parsed from `Canonicalizer.cs` and `moneyFields` from policy YAML — no hand-maintained list.


### 2026-09-10 — Banker Copilot task queue rendered empty over 10 live approvals

**Symptom:** `/copilot` Task queue showed 0 in all four buckets ("Nothing here.") while
`GET /api/authority/approvals?limit=200` returned 10 items for `banker`.

**The "10" was a red herring.** The footer "Signed this session 0 of 10" is
`config.sessionSignatureSoftLimit` (`copilotConfig.ts:129`), NOT an approval count. No count
of 10 ever reached the component. Chasing the bucketing logic on that premise would have
burned the whole window — `groupApprovals` in `TaskQueuePane.tsx` was correct all along and
reads exactly the fields the service emits.

**Root cause — double `/api` prefix, hidden by the SPA fallback:**
- `api/client.ts` created the axios instance with `baseURL: '/api'`.
- `authorityUrl()` / `copilotUrl()` in `config/copilotConfig.ts` return ABSOLUTE app paths
  (`/api/authority/approvals`, defaults at lines 113-114).
- axios concatenates: `/api` + `/api/authority/approvals` = `/api/api/authority/approvals`.

Verified live against the deployment, no credentials needed:
```
/api/authority/approvals      -> 401   (route exists, auth required)
/api/api/authority/approvals  -> 200   content-type: text/html  <!doctype html>...
```
The doubled path fell through to the SPA history fallback, which answers **200 with
index.html**. So nothing threw, no 404, no interceptor fired, and `listApprovals` hit its own
defensive `Array.isArray(data.items) ? ... : []` and returned an empty array. A silent
failure with a success status code.

**Scope was wider than the queue.** All four `api/copilot.ts` calls (`createSession`,
`startRun`, `sendMessage`, `fetchRunTrace`) were doubled identically — the whole harness was
dead, not just the queue. `api/copilotStream.ts` was NOT affected and must not be changed:
it uses raw `fetch`, not the axios instance, so it needs the full `/api/copilot/...`.

**Fix:** exported `API_BASE_PATH` and `apiPath()` from `api/client.ts`. `apiPath()` subtracts
the client baseURL, passes absolute URLs through, and `logger.error`s when the prefix is
absent rather than silently forwarding. Applied at the two path builders, not at ten call
sites. `baseURL` itself untouched — every other page depends on it.

Also made `listApprovals` log an error when a 200 body carries no `items` array. Returning
`[]` for a non-list 200 is precisely what hid this; an empty queue and an unreachable service
must not look the same.

**Lessons:**
1. **Absolute app paths + an axios `baseURL` is a silent-failure generator in an SPA.** The
   history fallback converts every mis-built API path into a 200 full of HTML. Prefer paths
   relative to the client, and never let a mapper treat an unexpected 200 shape as "empty".
2. **Check the denominator before trusting the numerator.** "0 of 10" looked like data
   reaching the component. It was a config constant that happened to equal the item count.
3. **An unauthenticated 401-vs-404 probe is a free routing test.** It separated "wrong URL"
   from "auth problem" without a token and without touching Brian's live seed.

**Also noted, not changed:** `toExecutionState` maps the wire's `"not_attempted"` to
`'not_started'` via its default branch. Semantically right, and grep confirms nothing renders
or gates on `executionState` today — inert, left alone.

**Bucket-count divergence (raised for Danny):** with the real payload the UI yields
7 / 1 / 1 / 1, not the 7 / 1 / 0 / 1 that `scripts/demo/demo.sh` prints. The UI puts the
`signed` item in "Running" (signed, awaiting execution) and the `denied` one in "Done today";
demo.sh calls the signed one done. Two classifications, one queue. Did not silently change
bucket semantics to match a shell script — decision written to the inbox.

**Tests:** `api/__tests__/approvalsRequestPath.test.ts` is the regression — it resolves the
URL the way axios does and fails on the old code with `Received: "/api/api/authority/approvals"`.
`components/copilot/__tests__/taskQueueBuckets.test.ts` feeds the real 10-item payload through
`toApproval` → `groupApprovals` as a contract guard. Suite: 444 passed, 13 failed, all 13 the
pre-existing account-opening failures (AgentPipeline, DocumentUpload). No new failures.

**Deployment note:** confirmed no runtime/env override for `endpoints.authorityBase` or
`copilotBase` anywhere in `src/ui-app/public`, the Dockerfile, nginx conf, or `infra/` — the
`DEFAULTS` (`/api/authority`, `/api/copilot`) are what actually ship, so the fix is verified
against the deployed values. **ui-app must be rebuilt and redeployed for Brian to see the
queue populate; a browser refresh will not do it,** since the served bundle still contains
the doubled path. Consumer audit clean: every axios call site is now `apiPath`-wrapped and
the only unwrapped `copilotUrl` caller is `api/copilotStream.ts:349`, the raw-`fetch` SSE
client, which correctly keeps the full path.

### 2026-09-10 (follow-up) — same root cause explains the dead centre panel; the grey Start does not

Brian widened the report: the centre panel also read "No run selected" and the Start button
looked disabled with the chip on "Idle". Both re-checked against the code and the live
deployment.

**Centre panel — same single root cause.** `submitIntent` calls `createSession`, which went
through the same doubled path. Probed live:
```
POST /api/copilot/sessions      -> 401 application/json  {"detail":"Missing Authorization header"}
POST /api/api/copilot/sessions  -> 405 text/html         <title>405 Not Allowed</title>   (nginx)
```
So the two HTTP verbs failed *differently* on the same doubled path, which is why the page
looked like three unrelated bugs:
- **GET** → SPA history fallback → **200 + index.html** → silent empty queue, no error at all.
- **POST** → static server refuses the method → **405** → `createSession` throws, caught in
  `submitIntent`, surfaced only as an 8-second snackbar.

No session ⇒ no `activeRunId` ⇒ `TracePane.tsx:399` renders `run ? run.title : 'No run
selected'`. One cause, three symptoms. The fix already made covers all of them.

**The grey Start button is NOT a defect — retracted.** `CommandBar` disables Start on
`busy || disabled || value.trim().length === 0`, and `CopilotHarness` **never passes
`disabled`** (grep for `disabled` in that file returns nothing), so it is `undefined`. On a
fresh page the only closed gate is an empty input box. "Idle" is likewise correct: it means no
session has been opened yet, which is the true state before the first intent. Nothing fetches
a capability or role to gate this control. Pinned by
`components/copilot/__tests__/commandBarGating.test.tsx`, including a guard that fails if a
`disabled` prop is ever wired in, so this diagnosis gets revisited rather than forgotten.

**Lesson — one bug wearing three masks.** A doubled base path produces *method-dependent*
failures: silent 200s on reads, hard 405s on writes. Symptoms that look unrelated (empty list,
dead panel, grey button) collapsed to one line of config. Resisting the urge to explain each
symptom separately was what kept the fix to three files. Corollary: two of the three "symptoms"
were not symptoms at all — the grey Start and the Idle chip were correct behaviour being read
as evidence. Confirm each reported symptom is genuinely anomalous before counting it.

Suite after the follow-up: 449 passed, 13 failed — the same pre-existing account-opening 13.

### 2026-09-10 (close-out) — the queue defect, settled end to end

Brian retracted the escalation (correctly — the grey Start was the empty-input gate) and asked
me to return to the queue panel, noting his point 2 was still open: *if the "10" is a hardcoded
constant, the component may be receiving nothing and the fault is in the fetch rather than the
bucketing.* That is exactly how it resolved:

- The **10 is a constant** — `sessionSignatureSoftLimit`, `copilotConfig.ts:129`.
- Therefore **the fault is in the fetch**, not the bucketing. `groupApprovals` was never wrong.

One nuance worth keeping: "the whole page receives no data" and "the queue panel is empty" were
never competing theories — they are the same defect seen at two zoom levels, because every
authority *and* copilot call shared the one bad path helper. Narrowing the symptom did not
narrow the cause.

Proved it with `components/copilot/__tests__/taskQueuePopulates.test.tsx`: mounts the real
surface with the real provider (not `offline`, so `refreshApprovals` actually runs), stubs only
the HTTP layer, and returns the live `banker` payload. The stub is **URL-aware** — it serves
data only to `/api/authority/approvals` and mimics the SPA fallback (index.html, status 200)
for anything else, so a returning double prefix reproduces the bug instead of passing on a
lenient mock. Observed both states:

```
PRE-FIX   ✕ requests the single-prefixed authority path
          ✕ shows 7 in "Needs you" — not the reported 0
          ✕ fills the other three buckets rather than leaving them all at zero
          ✕ shapes the queue to 5 visible with the rest behind "Show 2 more"
          ✓ renders an empty queue when the SPA fallback answers — the original bug
POST-FIX  5 passed
```

The last case is a deliberate reproduction of Brian's screenshot and passes in BOTH states —
it asserts the bug, not the fix. The other four are the regression.

**Method note for the team.** Three times in this session a reported "symptom" turned out to be
correct behaviour: the "0 of 10" footer, the grey Start button, the Idle chip. Each one, taken
at face value, implied a different and wrong root cause. The habit that paid off was tracing
every on-screen number and every disabled control to the line of code that produces it BEFORE
letting it shape a hypothesis — and being willing to tell the requester their framing was
wrong. Brian's own retraction proves the point better than I could.

Final suite: 454 passed, 13 failed — the same pre-existing account-opening 13. Nothing added.

### 2026-09-10 (final) — console trace confirms the diagnosis; misleading error fixed too

Brian's browser console independently produced what the code review and the live probes had
already established:
```
POST .../api/api/copilot/sessions  405 (Method Not Allowed)
  createSession @ copilot.ts:37 → CopilotContext.tsx:235 → CopilotHarness.tsx:96 → CommandBar.tsx:56
```

**Blast radius, enumerated (this was the part worth doing carefully).** Only TWO modules ever
built absolute `/api/...` paths and handed them to the axios client:

| module | style | status |
|---|---|---|
| `api/copilot.ts` | `copilotUrl()` → absolute | **was doubling** — fixed |
| `api/approvals.ts` | `authorityUrl()` → absolute | **was doubling** — fixed |
| `api/accountOpening.ts` | relative (`/applications/...`) | correct, untouched |
| contexts/pages (`/accounts`, `/auth/login`, `/transactions/my`, `/admin/*`, `/users/me/*`, `/chat`) | relative | correct, untouched |
| `api/copilotStream.ts` | absolute, but raw `fetch` — no baseURL | correct, untouched |

That table is the whole explanation for why login, nav and account pages worked while only the
copilot surface was dead, and it is why the fix had to go at the two path builders rather than
at the shared client. Changing `baseURL` would have broken every row marked correct.

**One bug, not two.** The queue fetch (`refreshApprovals` → `listApprovals`) goes through the
same doubled client, so the empty NEEDS YOU/WAITING/RUNNING/DONE TODAY panel and the rejected
harness request have a single cause. **There is no bucketing defect** — `groupApprovals` reads
exactly the fields the service emits and was never wrong.

**Second defect fixed (separate, real).** `CopilotContext.tsx:245` mapped every possible
failure onto "The harness did not accept that request. It is not running on the server." — a
statement about infrastructure the client cannot observe, presented as fact. Replaced with
`describeHttpFailure()` in `api/errors.ts`, which states the status, quotes the server's own
message via the existing `resolveApiError`, and treats 404/405 as *routing* faults rather than
outages. The log line now carries status and URL; the 405 was previously invisible in it.

**Cost of the bad message:** ~20 minutes chasing healthy pods and a token hypothesis that the
code had already ruled out (a stale JWT would have hit the `client.ts:59` interceptor and
force-redirected to `/login`, not left a signed-in user on an empty page). Worth remembering:
an error string that names a cause is a diagnosis, and a wrong diagnosis stated confidently
costs more than no diagnosis at all.

Final: **461 passed, 13 failed** — the same pre-existing account-opening 13, none added. `tsc`
clean. Needs a ui-app image rebuild + redeploy; the fix is not live in Brian's browser until then.

### Layout phase — `/copilot` responsiveness (Defects 1 & 2)

**The lesson: jsdom cannot see layout, so I stopped guessing and measured in a real browser.**
I wrote `tests/e2e/specs/layout-copilot.spec.ts` (Playwright, Chromium, 5 viewports incl.
Brian's 1550x780) and ran it against a static build. It immediately failed 8 assertions that
every unit test had happily passed. Every fix below came from a measurement, not a theory.

1. **The command bar was clipped, and the footer was NOT the cause.** I had assumed the
   marketing footer was eating the space. Measurement said otherwise: the command `Region`
   was rendering **24px tall** while the panes row above it kept 567px. Cause: the command
   `Region` inherited `flex-shrink: 1` and `Region` sets `minHeight: 0`, so flexbox was free
   to crush it below its content; the 40px input then overflowed into the column's
   `overflow: hidden` and vanished. Fix: `flexShrink: 0` on the command Region — it is the
   one row that must never shrink. Verified: region now 62px, bottom edge exactly 720/720.

2. **~950px of blank scrollable space below the surface.** The shell is `height: 100vh;
   overflow: hidden`, yet the document scrolled 964px into nothing. Cause: the shell was
   `position: static`, and **`overflow: hidden` does not clip absolutely-positioned
   descendants unless the element is their containing block.** The escapees were the
   visually-hidden `position: absolute` screen-reader spans in `ApprovalCountdown`. Fix: one
   line — `position: 'relative'` on the full-bleed container. This is a general trap: any
   `overflow: hidden` viewport shell needs `position: relative` or a11y-hidden spans leak.

3. **Do not trust `documentElement.scrollHeight` alone.** It read 1684 while `body`,
   `html` and `#root` all measured 720 — a contradiction. Screenshotting at scroll bottom
   (blank page) and reading `window.scrollY` after a `scrollTo` proved the scroll was real.
   When a measurement contradicts itself, add a second independent measurement.

4. **The right pane is NOT unreachable.** Before recommending anything for Defect 3 I
   checked whether the banker could physically reach the Sign button: the approval column is
   `overflowY: auto`, h 343 / scrollHeight 1032. Cramped, yes; blocked, no. Worth checking
   before escalating a UX complaint into a blocking bug.

5. **I broke a test and found it by counting.** The baseline is 13 failures; my run showed
   14. `agreementTriState.test.tsx` passed alone but flaked ~50% in the full suite. I did not
   wave it away as "flaky" — I stashed my changes and ran the original tree 4x (stable 13),
   which proved I had triggered it. Root cause: that test compares two rendered card texts
   and strips only `0.\d+`, but `ApprovalCountdown` re-renders on a 1s tick, so two renders
   straddling a tick differ by "MM:SS". My +34 tests slowed the suite enough to expose a
   latent time-dependent assertion. Fixed the strip regex. 5 consecutive full runs: 13/464.
   **Counting the baseline is what caught this. Always report the count.**

6. **A new spec must be checked against the *existing* config's collection.** The shared
   `tests/e2e/playwright.config.ts` has `testDir: './specs'` with no `testMatch`, so it would
   have swept up my layout spec and failed CI (it needs a local static server on :8099, not
   the deployed `BASE_URL`). Added `testIgnore: '**/layout-copilot.spec.ts'` and verified the
   split: main config collects 0 of them, `layout.config.ts` collects 30.

### Defect 3 — the centre pane now holds the selected approval

Brian ruled: build it (and suppress the FDIC footer — "this is a demo, not a regulated
deployment"). Implemented as one stateless rule, `runActive = Boolean(run)`:

- **A run exists → the trace owns the centre**, including after the run finishes. Reverting
  on completion would yank a trace away from someone still reading it.
- **No run → the centre shows the selected approval** (`ApprovalDetailPane`, a layout
  wrapper around the unmodified `ApprovalCard`, so every field survives the move).
- **No run → the artifact pane is not mounted at all.** It exists to show what a run
  produced; keeping it would reserve a third of the surface for one sentence and re-create,
  on the right, the very "large empty pane" defect being fixed.
- The swap is announced before it happens: the centre subtitle says the trace will take the
  pane, and the right-hand dock is now labelled "Selected approval" so it is findable.

**The lesson from this round: a pane measured EMPTY tells you nothing about the same pane
FULL.** Brian asked me to close the "trace with real run content" gap I had flagged. Doing so
immediately exposed a bug that had been latent for months:

> Every pane is the sole child of a `display: flex` Region, and **none had `flexGrow`**, so
> its width was CONTENT-based. `TracePane` looked correct forever because its empty-state
> paragraph is long; the moment a real run replaced it with short step labels the Paper
> collapsed to **426px inside a 750px region** — a 324px dead gap. Fixed on all four panes.
> Proved the guard works by reverting just that line and re-running: `Expected <= 2,
> Received 324`.

**And the reverse lesson, same round.** My stubbed run rendered a step as "NaN." — I nearly
filed it as a product bug. Instead I read the server: `planner/loop.py` sends
`{stepId, index, title}` on `step.started`, while my stub sent only `stepId`. The store does
`{...existing, ...patch}`, so my `undefined` index/title clobbered good values. **The stub was
unfaithful; the product was fine.** An unfaithful stub does not just miss bugs, it invents
them. (The store's overwrite-with-undefined is still latent fragility — flagged, not fixed:
it cannot fire against the real server and reducers are the wrong thing to edit mid-demo.)

**Baseline discipline paid off twice.** The count moved to 14 again and I did not wave it
through: the offender was MY `taskQueuePopulates.test.tsx`, which used `waitFor(async () =>
... await findByRole ...)`. A `findBy*` inside a `waitFor` callback spends its own retry
budget on every poll, so the suite passed alone (3s) and timed out under parallel load (13s).
Rewrote the callback to synchronous `getBy` queries — assertions unchanged. Five consecutive
full runs: **13 failed / 464 passed**.

### Phase 3 — the signing gate: every card was Deny-only

**Root cause, confirmed not assumed.** `canSignUnderStream` accepts only `live`/`resumed`;
`stream.status` initialises to `idle`; `openStream` had exactly ONE call site — inside
`submitIntent`. So a banker who loaded `/copilot` to work the queue and never dispatched an
agent run sat at `idle` forever and could not sign anything, **by construction**. Proven in a
real browser before the fix: zero requests to `/stream` on a cold load, against a stream
endpoint independently verified healthy. Not a backend fault, not a stale token.

**Fix.** Establish the session and stream on MOUNT, not on first dispatch. `POST /sessions`
executes nothing — the planner only moves when a run starts inside the session. The gate
itself was not touched: when the stream cannot be established, signing stays disabled. That
is the correct direction to fail.

**Learnings.**

1. **`route.fulfill` cannot hold an SSE connection open.** A fulfilled stream body is
   delivered then closed, which the client correctly reads as a disconnect — so a healthy
   stream looks broken and the test proves nothing. Verifying SSE needs a real server.
   `tests/e2e/support/fake_copilot_stack.py` is that server; reuse it.
2. **An unfaithful stub invents bugs — fourth time this month.** My stub did not drain the
   POST body, so on a keep-alive connection the body bled into the next request and produced
   a 400 that looked like a product fault. Separately, the layout spec's catch-all answered
   `POST /sessions` with `{}`, which tripped the client's sessionId guard and put an error
   toast on screen that read as a layout regression. Both were my harness, not the product.
   Before filing a defect against a stub result, check the stub against the real server.
3. **A "run once" ref plus StrictMode equals never runs.** React 18 StrictMode mounts,
   unmounts and remounts every effect in development. The unmount lands while the async work
   is in flight, so that attempt aborts — and the ref, already set, makes the remount skip the
   work entirely. The guard reintroduced the very bug the effect existed to fix, in dev only,
   invisible to a production build. Reset the ref in cleanup unless the work settled.
4. **A bottom-anchored toast is an occlusion defect.** MUI's `Snackbar` defaults to
   bottom-centre at `z-index: 1400` and landed squarely on the command bar — the same class of
   fault as Brian's footer complaint, and far easier to hit once errors could surface on mount.
   Found only because a real-browser `elementFromPoint` check failed.
5. **Do not weaken an existing test to fit new copy.** My gate wording dropped the phrase an
   older assertion depended on, then duplicated it so `getByText` found two nodes. The right
   answer was to split terse (beside the button) from full (in the alert), which is better UX
   and left the older guarantee intact.

### Phase 4 — the signing attestation said the opposite of the truth

**The check cleared the backend.** Before touching copy I compared
`requesterUsername`, `callerMaySign` and the slot rules in the live `banker`
payload. Slot 0 carries `minSeniority: 1` and an EMPTY `mustDifferFrom` — the
opening signature, which the requester may legitimately provide. Slot 1 carries
`minSeniority: 2` and `mustDifferFrom: [<requester uuid>]`. The service returns
`callerMaySign: true` for the requester only while slot 0 is unfilled, and flips
to false with "you cannot also approve it" the moment they fill it (item 7 in the
fixture proves it). **Separation of duties is intact. It was only ever copy.**

**The defect.** The attestation branched on `isL2` alone and never consulted the
slot, so every L2 signer was told they provided "the independent supervisor
co-signature ... because you are a different identity from the requester
(banker)" — while signed in AS banker. False for the opening signer, and
self-contradictory for the requester.

**Learnings.**

1. **The derivation already existed six lines away.** `SignatureRoster` had
   correctly computed "the slot the caller will fill" — first unfilled — and had
   even documented why. The banner just never used it. Before concluding a fact
   is not derivable client-side, grep for it: a sibling component may already
   derive it. Both now share one exported helper so they cannot disagree.
2. **Ordinals are not array indices.** `demoApproval` numbers its slots 1 and 2.
   Anything keyed off `ordinal === 0` silently mislabels every card built from the
   demo fixture while passing against the wire fixture. Key off slot STATE
   (how many remain unfilled), which is ordinal-agnostic and reads truer anyway.
3. **A test that asserts the buggy string locks the bug in.** `ApprovalCard.test.tsx`
   asserted `/independent supervisor co-signature/` was present. It was passing,
   and it was defending the defect. When a test's assertion IS the bug report,
   replace it with the inverse and say why in the test name.
4. **Derive the claim from what you can verify.** "You are the requester" is only
   claimed when `identity.id` actually matches `requesterUsername`; otherwise the
   copy falls back to neutral wording that is true either way. Failing to the
   weaker true statement beats guessing at the stronger one.
5. Rung is the wrong axis for this sentence entirely. Whether a signature OPENS
   an approval or CLOSES it is a property of how many remain, not of L1 vs L2 —
   which is also why the new copy survives Danny's possible third verb.

## Phase 5 — evidence findings (tool names -> what the agent learned)

**Defect.** The card listed only evidence *keys* ("Get user", "List login audits") and discarded
the payloads. The values were never missing from the API; they were dropped **client-side, in two
places**:

- `api/authorityWire.ts` `toEvidence` used the object key as a label and only filled `excerpt`
  from a nested `summary` string or a bare string value, so `{accountId, balance}` produced nothing.
- `ApprovalCard.tsx` `EvidenceList` rendered `item.label` only.

**Fix.** `EvidenceRef` gained `findings: PayloadField[]`, populated with the existing
`flattenPayload` + `humanLabel` primitives, so findings inherit the same formatting the payload
table already uses — `accountId` renders masked (`····6666`) and `balance` as `$59,480.00` for free.
Render is marked PROVISIONAL; Danny's card spec replaces the visual design, not the plumbing.

**GUID -> name is a solved problem, not backend work.** `GET /api/users/{id}` in `UsersController`
carries a plain `[Authorize]`, so a banker token resolves it today. `/admin/users` is
`[Authorize(Roles = Admin)]` and is NOT usable from the banker surface. There is simply no client
for it in `src/ui-app/src/api/` yet.

### Lessons

1. **`npx tsc --noEmit` is worthless in this project.** `target=ES5` + `moduleResolution=node10`
   emit TS5107 and abort *before* type-checking, so it reports clean while the app does not compile.
   It told me clean while `react-scripts build` failed on a real TS2322. **Use
   `CI=false npx react-scripts build` as the typecheck.** The whole team may be relying on `tsc`.
2. **A disclosure toggle that already reads "Hide X" is open.** My probe clicked it and closed the
   panel, then reported the data missing. The check was the suspect, again. Read `aria-expanded`
   (or the verb) before clicking, and dump the whole pane rather than a filtered subset.
3. **Verify a reported baseline before you accept blame for it.** The stated baseline was
   467 passed; measured, it was 473 (486 total, minus the one test that was asserting the *buggy*
   attestation string and correctly broke when I fixed the source). 473 + 9 + 5 + 2 = 489 exactly.
   Never explain a count delta — measure it by removing your own additions and re-running.


### 2026-09-10 — UI and Authority Fixes Session (#332)

**Session Type:** Multi-agent integrated session (Turk, Linus, Danny, Rusty)
**Branch:** `332-beta`
**Outcome:** UI defects fixed; pane architecture approved; approval card rebuilt

**Linus's Contributions:**
- Fixed doubled `/api/api` prefix by consolidating `apiPath()` source of truth
- Added `describeHttpFailure()` error messaging utility
- Fixed copilot pane layout: command bar clipping, blank scroll, flexGrow regression
- Implemented centre-pane architecture per Danny's ruling
- Fixed SSE terminal frame handling and reconnect-storm
- Preserved evidence findings field through wire mapping
- Updated signing attestation copy to banker-centric language
- Implemented session-on-mount pattern
- Verified: 489 passed, 13 pre-existing failures, 52/52 Playwright E2E

**Findings Flagged (awaiting Danny):**
- Queue bucket semantics: signed-but-unexecuted approval classification
- Footer compliance: FDIC text suppression acceptable?

**Orchestration Log:** `.squad/orchestration-log/2026-09-10T20:47:00Z-linus.md`
**Session Log:** `.squad/log/2026-09-10T20:47:00Z-copilot-ui-and-authority-fixes.md`

## Phase 6 — the reconnect storm and the heartbeat that never landed

Brian: 24 identical `GET …/stream?runId=…&lastSeq=6`, all 200 in 29ms, while the run had
already reached `run.done`. Four distinct causes, three of them mine.

1. **Heartbeats were dropped before they could pet the watchdog.** The real server emits
   `event: heartbeat` + `data: {"serverTs": …}` — **no `seq`, no `id:`** — so `toEnvelope`
   rejected it ("no numeric seq") and `armHeartbeatWatchdog` was never re-armed. A perfectly
   healthy idle stream was therefore declared `degraded` after
   `heartbeatIntervalMs * missedHeartbeatsBeforeDegraded` (30s shipped) and every card went
   Deny-only. **This, not the storm, is what Brian saw on a cold load.** Handle heartbeats at
   the FRAME level, before envelope parsing, and never require a seq of them.
2. **No terminal handling.** `run.done` was dispatched to the reducer (hence "completed ·
   1 steps" on screen) but `openCopilotStream` never looked at `event.kind`, so EOF after a
   finished run was indistinguishable from a dropped connection.
3. **`attempt = 0` on `response.ok`.** A 200 is not success — a session-scoped attach to a
   finished run answers 200 and ends immediately. Resetting the backoff there turns
   200-then-EOF into an unbounded tight loop. Only a real frame may clear the backoff, and
   the status is now claimed on the first FRAME rather than on `response.ok`.
4. **Not mine:** the server cannot hold a session stream open once that session's latest run
   has finished (`latest_for_session` returns closed runs; the `await_next_run` wait loop is
   only reachable when a session has never had a run). Routed to Turk, not worked around —
   see `.squad/decisions/inbox/linus-session-stream-cannot-outlive-a-finished-run.md`.

Also: `seq` is scoped to the RUN (`bus.py`: `RunStream._seq`), so the resume cursor MUST be
reset at a run boundary. Carrying run A's cursor into run B makes the server replay from
seq+1 and silently swallow run B's opening frames.

### Lessons

1. **My stub lied again — sixth time.** It sent `{"kind": "heartbeat", "seq": n}`. One
   invented field, and the Phase 3 gate spec passed green while the heartbeat-drop bug was
   live in production the whole time. Diff the stub against the real emitter, field by field,
   before trusting a green run.
2. **`addInitScript` cannot configure this app.** `public/runtime-config.js` *assigns*
   `window.__RUNTIME_CONFIG__`, clobbering anything set earlier. My first spec therefore ran
   with the shipped 30s watchdog, waited 12s and "passed" against the unfixed client. Route
   `**/runtime-config.js` instead, and ASSERT the override landed.
3. **Sampling once cannot see a flap.** The pre-fix failure is live → degraded → live within
   a few hundred ms. A single assertion after the window lands in a `Live` phase and reports
   all-clear. Sample continuously and judge the whole window.
4. **jsdom has no `ReadableStream`, no `TextEncoder`, no `TextDecoder`.** Without polyfills
   the decode step throws inside `connect()`, the error is caught as a lost connection, and
   every frame vanishes — the suite then reports a reconnect loop that is an artefact of the
   test environment. Supply `body.getReader()` directly and polyfill the codecs from `util`.
5. **A test that passes before the fix proves nothing.** Two of my four new unit tests passed
   against the pre-fix file; I rewrote one into a real discriminator and kept the other as an
   explicitly-labelled regression guard for the new code. Always run new tests against the
   unfixed source.
6. **Check what HEAD is before using `git checkout` as a time machine.** A commit landed
   mid-session and swept my working tree into it, so a "pre-fix" run silently tested the
   fixed code. Pin the parent SHA (`git show <parent>:<path>`) instead of trusting HEAD.

### Phase 6 addendum — the run timer, and two more tests that passed for the wrong reason

`TracePane` recomputed `now - startedAt` on every tick and ignored the `durationMs` that
`run.done` carries and the reducer already stores, so a run the service finished in 241ms
displayed "181s and counting" beside "the agent is still running on the server". Two lies on
one line. Prefer the server's number the moment it exists; sub-second runs now render "0.2s"
rather than flooring to "0s", which reads as a missing value.

7. **`getByRole('button', { name: /sign/i })` matches far more than the Sign button.** It also
   matches the batch group's "Sign 2 items" and every queue row whose accessible name contains
   "DENIED". My gate test passed in 525ms against one of those while the dwell-gated button it
   was supposed to be watching was still disabled. **A suspiciously fast pass is a failing
   test.** Enumerate what a selector actually matched before trusting it — `/^Sign — /` is the
   card's button, and it correctly reads `Sign — … (enabled in 0:26)`.
8. The gate now passes HONESTLY and untouched: pre-fix build, Sign is still `disabled` after
   40s; post-fix it enables at 26.6s, after the full L2 dwell. Both measured in a real browser.

## Phase 7 — Danny's approval-card IA spec, §7 steps 1/3/4 + option A

**Built** `components/copilot/approvalNarrative.ts` — pure functions, wired into `ApprovalCard`:
- `approvalHeadline` (§3.1): verb-first ask with the money. Unknown action → falls back to
  `actionLabel`. That fallback IS the safety property: a card that does not know an action must
  degrade to today's wording, never to a confident sentence about the wrong thing.
- `subjectAbsence` (§3.2, honest-absence form): §6.1 is Turk's and has not landed, so the card
  says plainly that it cannot identify the customer instead of printing a GUID as if it were an
  answer. Returns null when there is no customer subject.
- `whyThisRung` (§3.7/§6.4, client-side by Danny's assignment): replaces "Base rung … No
  escalators fired." Keyed on action AND rung together — keyed on action alone it would
  confidently tell a single-signer approval it "always needs two people". The escalator branch
  is untouched and still renders server text verbatim; that text is audit record.
- `expiryConsequence` (§3.8), `DENY_IS_FINAL` (priority 3, before the click).
- Action row restructured for THREE verbs; third slot deliberately EMPTY, not a disabled button.

**Two lessons, both the same lesson.**
1. `flattenPayload` keys rows on `path`, not `key`. My `.key` lookup returned undefined for
   every field, so all five sentences silently degraded to their fallbacks — and the fallbacks
   are plausible, so the card looked fine. 6 of 22 tests caught it. Read the producer's shape;
   do not assume the obvious property name.
2. **The browser caught what 22 unit tests could not.** Against expired fixtures the card read
   "If nobody signs by 4:06 PM, this is automatically denied" on an approval whose window had
   ALREADY closed — a future-tense forecast about a thing that has already happened. My tests
   passed because they used a fixture I read as current. `expiryConsequence` now takes `now`
   (fed by `useNow()`) and returns null past expiry. Third time this session the browser has
   found a defect the unit tests were structurally incapable of seeing.

**Verified:** 518 passed / 13 failed (13 = the two pre-existing account-opening suites,
unchanged); narrative suite 23/23; layout 52/52 in a real browser, twice; `CI=false
react-scripts build` compiles.

## Phase 8 — terminal-state signing affordances

**The defect:** a card whose signing window had closed still read "SIGNATURE REQUIRED" and
"Yours is the only signature needed — this goes ahead once you sign." A second report: `Deny`
stayed enabled and red on a fully SIGNED approval.

**Root cause — terminality is not a status.** The card's `terminal` flag was
`status === 'denied' || status === 'executed'`. Expiry is not a status: the service had not yet
swept the record, so it arrived `pending` with `callerMaySign: true` while the countdown three
lines above rendered "signature window closed — DENIED" from an independent time comparison.
`signed` was missing too — terminal for SIGNING, non-terminal for execution.

**Fix:** one predicate, `signingClosed(approval, now)` in `approvalNarrative.ts`, driving the
header, the aria-label, the attestation, and the WHOLE action row — including the reserved
third verb, so counter-propose cannot inherit the bug. Rule: an affordance renders only when
acting on it can change the record. It only ever narrows, so it cannot weaken the gate.

**Checked the server before touching the UI:** `ApprovalService.cs:446-455` rejects a deny on a
signed record with a 409. Purely a UI honesty bug, no escalation.

**Lesson — my own rule, nearly missed.** My first signed-record browser test PASSED while
asserting `getByRole('button', {name: /^Deny$/}).toHaveCount(0)` — because the card never
rendered at all. A signed record is not auto-selected. Assertions about the ABSENCE of
something pass trivially when the thing that would contain it is absent; always assert
something POSITIVE about the rendered surface first (here: the header text).

**Second-order find:** `demoApproval.expiresAt` was pinned to May 2026, four months lapsed, and
`demoEvents` feeds the replay path in `BankerCopilotPage`. Once this fix deployed, the scripted
demo would have opened on a fully suppressed card. The card was right; the fixture was stale.
Anchored that ONE window to load time; every other fixture timestamp is narrative and stays fixed.

**Verified:** 524 passed / 13 failed (13 pre-existing account-opening); layout 52/52; two new
real-browser terminal-state guards. 16 tests broke mid-change and were fixed by re-dating stale
fixtures, never by deleting assertions.

## Phase 10 — free-text planner run outcomes (2026-09-10)

- **The wire, read from the code not the design doc.** Answer artifact is
  `artifact.created` `kind:"answer"`, content `{answer, keyPoints[],
  citedEvidenceIds[], unverified[]}`. Refusal is `run.error {code, message,
  recoverable:false}` + `step.failed` + `run.done status:"failed"`. Turk's design
  wanted a durable refusal artifact; the code does not emit one, so a refusal
  exists ONLY as `run.error`.
- **Presentation, not placement.** The answer already reached the artifact dock —
  it rendered as a JSON dump because `ArtifactBody`'s last branch stringifies
  objects. Checking this before restructuring `CopilotHarness` saved putting 52
  layout assertions at risk for no gain. Always confirm which of the two a defect
  is before moving a component.
- **A constraint encoded in copy is not enforced.** I wrote non-disclosing copy
  for `ambiguous_subject`/`subject_not_found` and still passed the server message
  through verbatim. Non-disclosure held only because Turk wrote careful strings.
  Enforce at the render, and test with a deliberately leaky input.
- **See the control fail before trusting it.** Removing the guard made the test
  report three candidate usernames in the DOM. Same discipline caught the
  pre-fix/post-fix signature for the answer and refusal e2e: all three fail
  against the previous build, all pass against the current one.
- **The replay filter is a liability for anything carried once.** A refusal rides
  `run.error` alone, so a cold load depends entirely on the backlog passing the
  filter added with the storm fix. It does — `completedRuns` is empty on a fresh
  client — but that had to be asserted, not assumed. Durable across reload,
  LOST on service restart.

### 2026-09-10 — Session stream lifecycle bug found (#332)

**Issue:** When a session has completed at least one run and that run is finished, attaching to the session (no explicit `runId`) resolves to the closed run, immediately replays backlog, and disconnects (200-EOF). The client cannot hold a stream open at all, so signing buttons go dead until page reload.

**Root Cause:** `routes/sessions.py` `latest_for_session()` returns closed runs. The wait loop that would otherwise re-enter for the next run (`await_next_run()`) is never reached because `stream is None` is false.

**Proposal (deferred to server):** When no `runId` was requested and the latest run is already closed and fully replayed, fall through to the same `await_next_run` loop rather than replaying-and-returning.

**Client-side mitigation (implemented):** Stop hammering; stop re-dispatching the closed run's frames; report accurate run state rather than faking liveness. The gate must not sign without live stream freshness, so faking liveness weakens control.

**Verification:** `tests/e2e/specs/stream-lifecycle.spec.ts` with `STREAM_MODE=completed-run` measures stream requests before/after fix: 15 requests in 12s before, 5 requests after.

**Key Learning:** Signing gates depend on stream liveness as a freshness oracle. If the client cannot hold a stream open, it must not sign. A gate-weakening workaround trades correctness for demo convenience — do not do it.

## Phase 11 — a Playwright suite against the DEPLOYED surface (2026-09-10)

`tests/e2e/cloud.config.ts` + `tests/e2e/cloud/`. The first config here that leaves
localhost. Everything below was learned by probing `onlinebankingdemo.bjdazure.tech`, not
by reading the design docs; where the two disagreed the host won.

**The gate is a THROW, not a skip.** `run-outcomes.spec.ts` uses `test.skip` correctly —
the other mode genuinely cannot run. It would be wrong here: a skipped collection exits 0
with "0 failed", which reads as a pass, and that exact failure mode cost us the evening.
Unset `BANKER_COPILOT_CLOUD_E2E` → exit 1, no browser starts, no "passed" line anywhere in
the output. Verified, not assumed. The throw is duplicated at spec-module scope because a
spec can be reached by another config.

**Separation verified by counting, not by reading.** `playwright.config.ts` globs
`./specs` with a `testIgnore` of only two files — a cloud spec dropped in `specs/` would
have been silently collected by the offline suite and made CI network-dependent. Hence
`tests/e2e/cloud/`. `--list` across all five existing configs: 0 cloud specs collected,
495/52/4/2/4 tests, unchanged.

**Findings on the deployed surface.**
1. The approvals path in the brief, `/api/approvals?scope=all`, answers **200 with the
   SPA's index.html** via the history fallback. A successful non-JSON response is worse
   than a 404. Authority is at `/api/authority/approvals`.
2. **Nothing links a run to its approval in the UI.** The harness auto-selects the first
   pending signable approval on mount and deliberately never re-points the dock, so after
   a successful propose the dock still shows an unrelated queue item. Queue rows carry no
   id. I dock by clicking rows until the card's `payloadHashShort` chip matches the record
   authority returned — positive identification, loud failure if no row yields it.
3. **"No approval dock" is not assertable in the cloud, and asserting it would be a lie.**
   The dock is fed by the queue, not by the run, and a live tenant always has open items.
   What the requirement means is that the run PROPOSED nothing, so the assertion is an
   authority delta against a pre-run snapshot. Documented in the test rather than faked
   with an intercepted empty queue — that would only test the fake.
4. **The approval dock is a CHILD of the `Artifacts and approvals` region.** My first
   answer assertions read `canvas.innerText()` and were contaminated by the docked card:
   a strict-mode violation on `Cited evidence` exposed it, and the length and no-JSON
   assertions would otherwise have been satisfied by the CARD, not the answer. Subtract
   the dock text.
5. **`proposed` → `pending` is a real transition and polling catches both.** Asserting
   `pending` lost a race it had no business running. `TaskQueuePane` already groups both
   as open; the invariant is "open and awaiting people", not the label in that instant.
6. **A red test that does not say what the system did instead is nearly worthless.** The
   first L2 failure was "expected 1, received 0" after 4.1 minutes and cost another full
   run to diagnose. Both waits now watch for a refusal and fail carrying its code.

**Non-disclosure assertion, corrected by running it.** Built from the dataset, it first
failed on `banker` — because the refusal copy reads "Nothing matched the reference for
this banker", which is the READER's own role, not a customer. Scoped to `retail: true`
identities. Also asserted the candidate list is non-empty, so the loop cannot pass
vacuously.

**What the cloud actually does, over ~9 runs.** Approval and refusal: solid. Read-only:
about 3 in 4. Two distinct refusals observed on the SAME prompt that passes otherwise —
`planner_model_unavailable` at "Answer from evidence", and `intent_contract_invalid`
whose message is *"The answer model cited evidence this run did not gather:
['188470c5…', …]"*. So the contract failure Brian hit is citation validation: the answer
model cites raw record GUIDs while the run's evidence keys are `lookup_customer`,
`list_customer_accounts`, `resolved_subject`. Not a userId problem. Handed to Turk.

**No retries in this config, on purpose.** A retry would hide precisely the intermittent
cloud faults the suite exists to surface.

**Post-commit addendum.** A later full run failed the L2 test with `read ECONNRESET`
mid-body on `GET /api/authority/approvals?scope=all` — a 111KB response, polled every 3s
for four minutes, ~9MB through istio-envoy for one wait. Backed off to 5s. Polling is not
the thing under test and must not be the thing that fails. The same run's underlying
problem was real though: the propose path normally lands in 12-16s and occasionally does
not land inside 240s at all. Two consecutive re-runs afterwards: 16.2s and 12.7s, both green.

**Second addendum — refusal code drift, and assertion ORDER.** After Turk's identifier
fix landed, the unknown-customer prompt refused once as `objective_unmappable` instead of
`subject_not_found`, and my assertion on the code ran BEFORE the non-disclosure checks —
so the run that drifted told me nothing about whether the copy had leaked. Reordered: the
named-code check and the whole non-disclosure block run first and hold whatever the code
is; the subject-code expectation is asserted last, alone. It is not pedantry about naming:
`TracePane` suppresses the server's message for `subject_not_found` and `ambiguous_subject`
and for nothing else, so an unresolvable customer refusing as `objective_unmappable` puts
the server's own sentence back on screen and returns non-disclosure to being a property of
whoever wrote that sentence. Worth a ruling. Lesson: put the SAFETY assertion before the
IDENTITY assertion, or a change of identity hides the safety result.

**Also observed:** the whole host went unreachable for ~15 minutes mid-session (curl
timeouts, then 503 from authority behind a reachable ingress). The suite reported it
precisely — "Expected 200, Received 503" against the exact URL — rather than as a mystery
timeout. That is the behaviour I wanted from it.

**Third addendum — the subtraction that subtracts nothing.** `canvasText.replace(dockText, '')`
no-ops silently when the two renderings differ by a newline, which would quietly restore
the dock contamination the subtraction exists to remove — an absence-style trap wearing a
different hat. Now asserted: when a dock is present, the subtracted text must be shorter.

**Post-fix read-only rate.** After `5b53da4`, over seven runs: four green, three refused,
all three `planner_model_unavailable` with the server message *"The answer model could not
be reached (ChatClientException)"*. So the CONTRACT failures are gone and what remains is
the answer model's endpoint being unreachable about two times in five. Different problem,
different owner. `intent_contract_invalid` has not recurred since the fix.

**Left in the demo tenant:** 12 pending/denied `$35.00 goodwill credit` approvals from the
L2 test, in a queue of 25. None signed. Worth a sweep before Brian demos from that queue.

## The finding this suite was built to catch (2026-09-11)

`Refund a $35 overdraft fee on retail's checking as goodwill`, unchanged, proposed
**`direction: "debit"`** with the reason *"Goodwill refund of overdraft fee"*. Thirty-five
dollars taken OFF the customer instead of given back — and because a debit does not trip
the `credit-adjustment` escalator, the approval came out **L1, one signer, no escalators
fired**. The three runs before it were all `credit` → L1 raised to L2, two signers.

So the dual-control guarantee on credits is only as good as the direction the model picks,
and the model does not always pick it. The record is internally consistent — authority
applied its policy correctly to a debit — which is exactly why nothing downstream can
catch this. The card even reads "Take $35.00 off a customer's account", so a banker
reading carefully would catch it; a banker signing an approval titled "goodwill refund"
would not.

Assertion order changed to name the cause: direction first, rung second. Asserting the
rung first reported "expected L2, received L1", which is the symptom. Third time tonight
the same lesson — the assertion that states the SEMANTIC truth goes before the assertion
that states the consequence.

**Cloud rates over ~20 runs, post-`5b53da4`:** refusal test solid; read-only about 3 in 5,
every failure `planner_model_unavailable` ("The answer model could not be reached
(ChatClientException)"); L2 about 4 in 5, failures split between `objective_unmappable`
("no proposable action supports posting or refunding a fee directly in this harness") and
the debit inversion above. None of these are UI defects. All three are model or
environment non-determinism sitting directly under Brian's demo script.

## Phase 11 — a security assertion that could not tell a leak from a timeout

**The defect.** `tests/e2e/cloud/banker-copilot-cloud.spec.ts` asserted subject
non-disclosure with `expect(refusalText).not.toMatch(/\d/)`. A cloud run failed
it on the `30` in "The planner model did not answer within 30s". Nothing leaked.

**The lesson, which generalises past this file.** A proxy assertion fails in both
directions at once. Red becomes uninformative — an infra timeout and a customer
data leak render identically, so the red gets discounted. And green becomes luck:
it passed only because Turk happened to word the other refusals without digits.
Danny's phrasing is the one to remember: *non-disclosure held only because someone
wrote careful strings; that is not a control.*

**What replaced it.** Three assertions, scoped:
1. no candidate identifier (derived from `config/demo-dataset.json`, not retyped);
2. no COUNT, matched as *a number quantifying records*, which cannot fire on a
   timeout, a currency amount or a date;
3. for the two codes the ruling covers, the strong form — subtract every string
   this repo authored from the rendered notice and require an empty residue.
   `TracePane` drops the server message for those codes, so residue *is*
   server-authored text on screen, and that is the only channel a candidate name
   can travel on.

**Import the enforcing module, do not mirror it.** The spec imports `refusalCopy`
and `isNonDisclosing` from `src/ui-app/src/components/copilot/runOutcome`. A
second copy of `NON_DISCLOSING` in the test would drift from the guard at
`TracePane.tsx:68`, and a disclosure test that has drifted is worse than none.
(Cross-package import depth from `tests/e2e/{specs,cloud}/` is `../../../`.)

**Infrastructure is not a security finding.** `planner_model_unavailable` now
bails out by name with a loud annotation. The run never reached subject
resolution, so there is no subject outcome to assert on. Residual risk, stated
rather than hidden: a permanently unreachable model would leave the property
silently unverified. It is visible as a skip in the report, which is the trade.

**How the proof nearly fooled me — the advisor caught it.** My first leak mode
used `subject_not_found` with a leaking message. That code is non-disclosing, so
`TracePane` suppresses the message, the residue is empty and the check *passes*.
I would have shipped a "leak is caught" test that never saw a leak. Retargeted to
`objective_unmappable` — a DISCLOSING code carrying the same candidate-naming
message, which is exactly Danny's open gap that `reasonCode` has no enum. That
renders verbatim, so the leak really is on screen.

**Redact with the derived list, never a hand-typed one.** The residue test first
failed with "the refusal must not name Rita" because my inline
`/Mbeki|Kowalski|casey|.../` redaction missed a first name that `candidateNames()`
knows about. Same class of bug as the assertion being fixed.

**Both directions, against rendered `innerText`, never synthetic strings.** The
residue subtraction is about the component's actual chrome — its headings,
separators, punctuation. A version validated against hand-written text would have
been the next false positive.

New fake-stack modes: `leaky-refusal`, `suppressed-refusal`, `model-unavailable`.
Commit `cdab02b`. jest 541/13 unchanged.
