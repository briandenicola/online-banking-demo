# Linus — History

## Project Context
- **Project:** online-banking-demo — AI-generated online banking application
- **User:** Brian
- **Stack:** React/TypeScript, MUI, Create React App
- **App:** ui-app — the frontend banking interface

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
