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
