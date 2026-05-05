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
