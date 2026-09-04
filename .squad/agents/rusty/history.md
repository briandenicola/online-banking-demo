# Rusty — History

## Core Context

- **Project:** online-banking-demo (Brian Denicola). Microservices banking demo on AKS + Azure.
- **Stack:** C#/.NET (user, account, transaction, transfer, prompt-eval), Python/FastAPI
  (ai, budget, chatbot, account-opening), Go (event-processor), React/TS (ui-app),
  Redis, Cosmos DB, Terraform, Taskfile.
- **Joined:** 2026-09-04, to fill the platform/infra lane left open when Basher was retired,
  and to parallelize Phase 1 of the Banker Copilot epic (#332).

## Verified findings inherited on day one

These were verified against source during the #332 design round. Treat as known-true:

1. **Shared JWT audience + symmetric key (#334).** Every service validates audience
   `banking-demo`, and signing is HmacSha256 with a `SymmetricSecurityKey`
   (`src/user-service/Services/AuthService.cs:41-43`). Symmetric means every service holding
   the validation secret can also MINT tokens — forge, not merely verify. This is load-bearing
   for #332: without a distinct mediator-only audience, an agent can bypass `authority-service`
   and call `transfer-service` directly, making the approval ladder decorative.
2. **Audit gap (#335).** `src/event-processor/main.go:403-410` switches on only
   `TransactionCreated` and `TransferInitiated`. Other published event types fall through to the
   unknown-event branch and are published-but-unaudited.
3. **Single shared workload identity (#336).** One shared UAMI with account-scoped Cosmos Data
   Contributor means services are indistinguishable to the mesh, and per-service data isolation
   is a naming convention rather than a control.
4. **nginx lacks `proxy_buffering off`.** Neither `infra/local/gateway.nginx.conf` nor
   `ui-app.nginx.conf` disables buffering, so SSE would arrive as one lump at the end.

## Learnings

### 2026-09-04 — Phase 1 platform slice for epic #332 (Banker Copilot)

Branch `squad/332-banker-copilot`. Turk built `authority-service` in parallel; I did not
touch `src/authority-service/`.

**Verified against source, not documents:**

5. **The audit gap was bigger than #335 recorded.** #335 named the Copilot events. Reading
   the producers turned up two event types that have *always* been published and *never*
   audited: `InsufficientFundsAttempt` (`transaction-service/Services/TransactionService.cs`,
   `PublishInsufficientFundsEvent`) and `UserRegistered`
   (`user-service/Services/UserService.cs`, `PublishUserRegisteredEvent`). Both landed in
   the Go `default:` branch. An insufficient-funds attempt is precisely the kind of signal an
   audit trail exists for. Lesson: when a doc lists "the events", enumerate the publishers.

6. **`docs/design/…policy-engine.md` §7.2 and epic §5.2 describe different approval
   documents.** `signatures[]` vs `signatureSlots[]`, `proposedAtUtc` vs `createdAt`,
   top-level vs nested `policyVersion`/`requiredRung`, and a `cosignerId` pointer document
   that exists only in the epic. I indexed the design doc's shape because it is the document
   that carries the query analysis. Filed as
   `.squad/decisions/inbox/rusty-approval-schema-drift.md`. **This is the dangerous class of
   drift:** Cosmos returns *zero rows*, not an error, when a field path is wrong, so the
   whole thing looks like "no approvals yet".

7. **Epic §5.8.3's `authority.role.granted` cannot work.** The Go consumer switches on exact
   PascalCase strings and every existing event on `banking-events` is PascalCase. The dotted
   form would have been silently unaudited — the one event whose job is proving a role grant
   was audited. Shipped as `RoleGranted`; filed
   `.squad/decisions/inbox/rusty-role-granted-event-naming.md`.

8. **`admin` needs a *seniority* of 0, not just an empty `implies` list.** Making
   `admin → []` stops admin *implying* supervisor, but if admin still carried a high
   seniority number it could satisfy a `minSeniority: 2` signature slot directly and defeat
   separation of duties by a different route. Banking seniority and platform power are
   separate axes all the way down, not just in the implication graph. Locked with a test.

9. **`azurerm_federated_identity_credential` in this repo omits `resource_group_name`.**
   Adding it (habit from azurerm 3.x) fails validate under `~> 4`. Match the existing
   resource in `identity.tf`.

10. **`go fmt` rewrites more than you edited.** `main.go` and both existing test files were
    already non-gofmt-clean. I kept the `main.go` reformat (file I was in) and reverted the
    two test files to avoid unrelated churn in someone else's diff.

11. **Cosmos scoped data-plane role assignments** take a `scope` of
    `<account-id>/dbs/<db>/colls/<container>` on `azurerm_cosmosdb_sql_role_assignment`.
    That is how `authority-service` gets the approval store and nothing else.

12. **Pre-existing broken test, not mine:** `src/user-service.Tests/CosmosSDKVersionTests.cs`
    hardcodes `RepositoryRoot = "/home/brian/code/online-banking-demo"`. This checkout is
    `foundry-online-banking`, so four tests fail with `DirectoryNotFoundException` on a clean
    tree. Left alone (unrelated to #332) but it makes the suite permanently red and hides
    real regressions. Worth a one-line fix by whoever owns test infra.

13. **SSE needs `proxy_buffering off` at BOTH hops.** The browser reaches the harness through
    `ui-app.nginx.conf` → `gateway.nginx.conf`. Disabling buffering only on the gateway
    achieves nothing; ui-app re-buffers the stream it just received. Also needed:
    `proxy_read_timeout` well above the default 60s, because an SSE connection is idle
    between frames by design and nginx will otherwise cut a healthy trace at one minute.

14. **The `set $upstream …` + `resolver` idiom in `gateway.nginx.conf` is load-bearing for
    docker-compose.** With a literal `proxy_pass http://authority-service:8080`, nginx
    resolves at *startup* and refuses to start when the container is absent — which would
    have broken local dev the moment I added a route for a service Turk had not finished. The
    variable form defers resolution to request time, so an unrouted prefix is a 502 rather
    than a dead gateway. Follow it for every new route.
