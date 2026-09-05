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

### 2026-09-04 — Phase 2 platform slice for epic #332 (Banker Copilot harness)

Branch `squad/332-banker-copilot`. Turk built `banker-copilot-service` in parallel; I did not
touch `src/banker-copilot-service/`, `src/ui-app/` or `src/authority-service/`.

**Reading the implementation beat reading the documents again — three times.**

15. **`Artifact.to_document()` uses a bare `asdict()`, so it persists snake_case, while
    `list_artifacts` queries `c.runId`.** `Session` and `Run` explicitly re-add the camelCase
    keys after their `asdict()`; `Artifact` only adds `artifactId`. So the artifact documents
    have `run_id`/`session_id`, the query reads `runId`, and the container's declared
    partition-key path `/sessionId` is *absent from the document entirely* — every artifact
    would land in the undefined partition and every read return zero rows. Neither the epic
    nor the design doc could have told me this; only the store code did. Lesson 5 generalises:
    **when a doc lists "the schema", read the serializer.**

16. **Composite index DIRECTIONS have to line up, not just the paths.** Phase 1 taught me that
    Cosmos ignores a composite index unless every filter and ORDER BY path appears in it, in
    order. The half I did not know: a composite index serves an ORDER BY only when the
    directions match exactly *or are exactly reversed for every path*. I had declared
    `(runId ASC, revision DESC)` against a service issuing `ORDER BY c.revision` **ASC** — that
    index does not apply. Same silent signature as a wrong path: correct rows, full scan, looks
    healthy. `copilot-artifacts` now declares both directions.

17. **`copilot-sessions` PK: the epic said `/id`, the code said `/sessionId`, and the code was
    right.** §2.4 was written when the container held only sessions; the service also stores
    RUN documents there, whose `id` is the run id, so `/id` would put every run in its own
    partition and destroy the co-location the single container exists for. Changed to
    `/sessionId` and filed the deviation rather than following the older document — same basis
    on which Danny made design §5.3 authoritative over the epic. Nothing regressed because
    `Session.to_document()` sets `sessionId = id`.

18. **My own Phase 1 `chunked_transfer_encoding off` was a bug, and a subtle one.** The design
    doc says `on`; I shipped `off`. With no `Content-Length` and no chunking, nginx delimits the
    response by *closing the connection*, which makes a mid-run network drop byte-for-byte
    indistinguishable from a clean end of stream. `fetch()` reports normal completion, the §4.5
    reconnect never fires, and the UI sits on a frozen trace that still says "live" — the exact
    thing §4.6 forbids, defeated *below* the layer any client-side guard operates at. Removed at
    both hops. **Verifying my own previous phase against the design doc found this; nothing else
    would have.**

19. **`authority-service` was never added to `tasks/Taskfile.build.yml`.** Phase 1 shipped its
    manifests, its identity, its ConfigMap keys and its gateway route — and nothing that builds
    the image. A cloud deploy would have reached `ImagePullBackOff`. The kustomize `images:`
    block listing an image is not evidence that anything produces it; those are two independent
    lists and only one of them is exercised by `kubectl kustomize`. Added both Copilot images.
    **Lesson: "it validates" and "it deploys" are different claims.** Everything I validated in
    Phase 1 was true and the service still could not have run.

20. **Two names for one value, three times over, in one service.** Turk's `config.py` reads
    `CosmosDb__Copilot*ContainerName` OR `COPILOT_*_CONTAINER`; the repo uses
    `FOUNDRY_PROJECT_ENDPOINT`/`FOUNDRY_MODEL` while this service reads
    `AZURE_AI_PROJECT_ENDPOINT`/`AZURE_AI_MODEL_DEPLOYMENT`. I set exactly one name per value in
    the ConfigMap and compose, and supplied the names the code actually *reads* rather than the
    ones convention prefers — a manifest that is conventionally correct and unread is a service
    with no model access. Reported both for convergence. The Phase 1 rule holds: **if config
    restates something, bind it or assert agreement; never restate.**

21. **Least privilege for an agent runtime is mostly about what you leave OUT, and the omission
    that mattered was Redis.** The reflex is to grant it "like the other services". But
    `banking-events` is the audit bus: granting it to the harness would give the one component
    defined by its inability to act the ability to forge an `ApprovalSigned` event. Containing a
    component in the data plane and then handing it the audit trail undoes the containment
    through the record rather than through the data. `authority-service` owns publishing (§5.7);
    the harness gets nothing. Same reasoning produced Cosmos Data **Reader** (`…0001`) rather
    than Contributor on `copilot-approvals` — one character, and it is the invariant.

22. **The Key Vault grant is an honest hole and I said so in the file.** The harness must read
    the JWT signing key to verify banker tokens, but #334 makes that key symmetric, so verify
    implies mint. Every other grant narrows the harness; this one hands it a supervisor token
    generator. It cannot be closed at the platform layer. **Consequence for how we talk about
    Phase 2:** we may not claim the harness cannot authorise its own actions — it cannot via
    Cosmos, the manifest or the gateway, but it can by minting. #334 now blocks two claims.

23. **A Terraform variable nothing consumes is a duplicate waiting to drift.** I wrote
    `banker_copilot_port` to "document the contract" with nginx, then deleted it: nginx cannot
    read Terraform, so it was a second statement of `8005` with nothing comparing the two.

24. **Environment verification limits, stated rather than glossed:** no Docker daemon and no
    nginx binary here, so `nginx -t` and any real SSE exercise were impossible. `terraform
    validate`/`fmt`, `docker compose config` and `kubectl kustomize` all pass; the nginx files
    were only checked structurally. The streaming path is unproven and needs one `curl -N`
    through both hops before the demo.

25. **Hyphenated ConfigMap keys are silently dropped by `envFrom`.** I first wrote the harness's
    read-tool upstreams as `DOWNSTREAM__account-service`, matching the hyphenated form
    `authority-service` uses in docker-compose. Compose is fine with it; Kubernetes is not.
    `envFrom` only injects keys that are valid C_IDENTIFIERs (`[A-Za-z_][A-Za-z0-9_]*`), so every
    hyphenated key is skipped — and since kubernetes#130099 **without even an event**. The pod
    would have come up healthy, passed both probes, and had every single read tool unresolvable,
    with the failure appearing only as "the agent can't find anything". Fixed to
    `DOWNSTREAM__ACCOUNT_SERVICE`, in compose too so the two modes cannot diverge; the service
    already lowercases and maps `_`→`-`. **Then I proved it** rather than reasoning about it:
    replayed Turk's `_collect_downstream()` against the real ConfigMap and the real compose file
    and asserted the resolved set equals the six `service:` values in `config/copilot-tools.yaml`.
    6/6 both modes, 0 keys dropped. Worth keeping as a standing check — the general rule is that
    **docker-compose is more permissive than Kubernetes about env var names, so compose passing
    proves nothing about the cluster.**

### 2026-09-04 — Phase 3 platform slice for epic #332 (supervisor queue, notifications, fan-out config)

Branch `squad/332-phase3-supervisor` (shared tree; Turk building the co-signature/batch engine
and Linus the UI in parallel — I touched only `authority-service` DI/notification code, the
harness config surface, and deployment wiring). Verified against source, not docs, again.

26. **The Q3 supervisor-queue composite index was already correct — the honest deliverable was
    proving it, not adding it.** `(status, awaitingSeniority, createdAt)` on `copilot-approvals`
    has been in `cosmos.tf` since Phase 1. I re-verified all three paths against the WRITER
    (`Approval.cs` `[JsonProperty]` + `ThrowingApprovalStatusConverter` → lowercase `"pending"`;
    `RefreshPendingSlot` maintains `awaitingSeniority`), not the design doc, because a composite
    index on a path the writer never persists fails the same zero-rows-not-an-error way a query
    does. No pointer doc / no `cosignerId` anywhere. Filed
    `rusty-phase3-supervisor-queue-index.md`.

27. **`authority-service` had NO `Redis__ConnectionString` in the kustomize base — so audit
    publishing (§5.7) was silently a no-op in AKS.** In-cluster it fell back to
    `NullAuditPublisher`; every approval event was published-to-nothing while passing both probes.
    Found it because the redis-stream notification sink needs the same connection. Added it from
    `banking-secrets/redis-connection-string` (the secret event-processor already consumes),
    which fixes the audit gap and enables the sink together. "It validated" ≠ "it published",
    third time this epic (Phase 2 lesson 19). compose already had it; only kustomize was missing.

28. **A notification is not an audit event, so it must not ride the audited bus.** The
    redis-stream `INotificationSink` defaults to a DEDICATED stream `copilot-notifications`, not
    `banking-events` (config-overridable). `banking-events` is a closed 11-type PascalCase
    vocabulary that `RedisAuditPublisher` throws on and the Go consumer switches on; a transient
    supervisor ping there is either forced into the audit enum or lands in the `default:` branch
    as another published-but-unaudited unknown. Same "read the consumer, not the doc" basis as
    `RoleGranted`. Filed `rusty-phase3-notification-sinks.md`.

29. **The §5.2.2 "kind of signer, never who" rule extends onto the wire.** The notification
    payload carries `awaitingSeniority`/`pendingSlotOrdinal`, never a co-signer id — a test
    asserts the envelope has no `cosigner*`/`assignee`/`reviewerId` field. Naming a co-signer in
    a notification is the same self-dealing hole the pointer doc was deleted for, one layer out.

30. **A config module in `app/planner/` named `*fan*out*.py` falsely trips the integration
    ledger.** My loader was `fanout_limits.py`; it instantly failed
    `phase3-supervisor-blind-construction` whose precondition glob is
    `absent:...app/planner/*fan*out*.py` = "the harness gained a real fan-out CONSTRUCTION path,
    promote the blind-construction test." A config loader is not that path. Renamed to
    `app/planner/limits.py` (frozen `FanoutLimits`, fail-closed). The glob is the right tripwire
    for Turk's engine; it should fire on the `asyncio.gather` path, not on the YAML it reads.
    Lesson: on a shared tree, another lane's tripwire can be armed by your filename. Filed
    `rusty-phase3-fanout-limits-config.md`.

31. **Fan-out limits are one file, loaded, never restated.** `config/harness-limits.yaml`
    (4/2/20/60, §6.3) is the single home; `limits.py` fail-closes on missing/malformed/unknown-
    version/non-positive; the test parses the numbers OUT of the epic so epic↔file↔loader drift
    fails loudly. Path-only through config.py/Dockerfile/compose/kustomize — no per-limit env var,
    because a second spelling of `4` is `4` wrong once (lesson 23).

**Environment limits (stated, not glossed):** dotnet 10, terraform, kubectl, kustomize, docker
CLI and python are all present — so `dotnet test` (207 authority + 294 harness green),
`terraform validate/fmt`, `docker compose config`, `kubectl kustomize` were ALL actually run and
pass. What I could NOT run: no Docker daemon and no live Redis/Azure, so an actual
`StreamAddAsync`, the webhook POST, and the end-to-end "supervisor's second browser gets the
ping" are unproven — unit-tested with fakes only. Build task, kustomize base, and gateway routes
already cover both Copilot services (no new microservice in Phase 3), so nothing new was
undeployable; verified rather than assumed.
