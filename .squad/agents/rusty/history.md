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

32. **Two escalators in `config/authority-policy.yaml` cannot fire through the propose API at all.**
    `EvaluationContext.BuildDocument()` overwrites `document["actor"]` from `ActorContext` and sets
    `context.selfDealing` from `ActorContext.SelfDealing`. `ApprovalsController` always builds that
    context with `_actors.Create(user, sessionId)`, where `SelfDealing` defaults to `false` and
    `SignaturesInWindow` is never read back from storage. So `self-dealing` (reads
    `context.selfDealing`) and `velocity` (reads `actor.signaturesInWindow`) are structurally
    unreachable no matter what facts a caller supplies. No seeder can demonstrate them; this needs
    an authority-service change. The other five escalators are fact-driven and do fire.

33. **Escalator `raiseBy` steps up from the rung the action's OWN rules already produced.** Demoing
    an escalator on `transaction.flag.review` over a large flagged amount goes L1 -> L2 (the
    `large-flagged-amount` rule) -> L3 (the escalator), and L3 proposals are refused outright — so
    the card the demo was built around never exists. Every escalator demo must sit on a payload
    that is still L1 when the escalator fires. There is now a static guard for this that evaluates
    each action's own rules against the seeded payload.

34. **`get_flagged_transaction` takes the flagged-record id, not the transaction id.** The copilot
    tool hits `/api/admin/flagged-transactions/{id}` where the id is the ai-service `scored_id`.
    Seed evidence with the raw transaction id and the tool 404s mid-run.

35. **`scripts/seed-data.sh` had three latent breakages**, all fixed: it posted to
    `/api/users/login` (405 — step 2 could never have worked), and used lowercase `checking` /
    `deposit` where the server DTO regexes are case-sensitive (`^(Checking|Savings|...)$`,
    `^(Debit|Credit|Transfer|Deposit|Withdrawal)$`).

36. **`admin` has seniority 0** in `config/role-hierarchy.yaml`, so it can neither propose, sign nor
    deny. Anything that closes approvals — including `demo:reset` — must use the supervisor token.
    Admin is only good for `/api/admin/*`.

37. **The empty copilot task queue had two independent causes, not one.** `CopilotContext` loads
    `scope=mine` (filtered on `requesterId == actor.userId`) plus `scope=awaiting-me`; with no
    approvals requested by the banker both are empty regardless of authorization. The separate
    authorization gap breaks evidence gathering *during a run*, not the listing. Fixing either
    alone leaves the demo broken.

38. **Reset against these services is necessarily partial.** No delete endpoint exists for accounts,
    transactions, Redis-held scored/flagged records or terminal approvals. Consequence found the
    hard way in testing: stale flagged records outlive the identities that produced them, so a
    re-seed picks a subject whose account no longer resolves to any seeded customer. The seeder now
    filters AI subjects to accounts owned by the current run, and reset prints exactly what it could
    not remove instead of implying a clean slate.

39. **A deliberately locked identity breaks its own re-seed.** The `user.unlock` subject cannot log
    in, and role verification depends on logging in. Unlock first, verify, then re-lock at the
    proper stage.

40. **`local:`/`cloud:` are includes, so an included taskfile can be included twice.** Wiring
    `Taskfile.demo.yml` into both with a different `DEMO_TARGET` gives `local:demo:*` and
    `cloud:demo:*` for free, and keeps one spelling of the local/cloud distinction rather than
    adding a second, unchecked one via a top-level namespace and a flag.

41. **Seed data was never the blocker for the empty copilot task queue — I was half wrong.** I had
    read it as primarily a data problem. Livingston seeded the environment for real and the queue
    stayed empty, because the queue renders approvals and *no run can produce an approval*. There
    are two independent server-side gates: Gate A (six read tools behind admin-only or
    owner-scoped endpoints the acting banker cannot read) and Gate B (the evidence contract in
    `config/authority-policy.yaml` demands objects with field names the tools do not return, and
    three tools return bare arrays, which `EvidenceComplete` can never accept). Fixing either
    alone unblocks nothing. Proof: run `run_5855e85caad34c12` — `account.balance.adjust`, no admin
    endpoint touched, both reads 200 with real data, still refused `evidence_incomplete`.

42. **Two individually reviewed config files can be mutually unsatisfiable.** `authority-policy.yaml`
    and `copilot-tools.yaml` each read fine alone. Nothing tested the seam between them, so the
    contract and the tool output disagreed silently for as long as the feature has existed. When
    two config files describe two ends of one wire, the test belongs on the wire.

43. **The tempting implementation of "approvals in every state" would make the demo lie.** Writing
    approval rows straight into the store puts cards on screen in every state while the propose
    path stays dead. It demos cleanly, survives review, and is false — the same class of defect as
    the scripted supervisor. `demo.sh` therefore creates approvals ONLY by driving
    `POST /api/authority/approvals`, probes the propose path first, and when it is closed it seeds
    nothing, says which gate is holding, and exits 3. A guard test enforces both halves and was
    tamper-tested.

44. **`get_account` is ownership-scoped, so evidence accounts must belong to the acting banker.**
    Accounts seeded onto retail customers are unreadable evidence and present later as a service
    bug. The dataset now gives the banker four accounts with deliberately different histories
    (routine, near-threshold structuring, high-volume, deliberately empty), one marked
    `evidenceSubject`, and the guard test fails if that account is owned by anyone but a banker.

45. **Idempotence has to survive accounts this seeder did not create.** account-service exposes no
    label or name to key on, so each desired account now CLAIMS the first still-unclaimed existing
    account of the same type and only creates one when nothing is left to claim. Verified against a
    reproduction of the live environment (three hand-made banker accounts, eleven transactions):
    reused all three, created only what was missing, disturbed nothing.

46. **`jq` gotcha that cost me two debugging cycles.** In `index(.key)` and `has(.)`, the `.` inside
    the argument is the *input to that function*, not the surrounding element. `$claimed |
    index(.key)` indexes the claimed array with the claimed array's own `.key`. Bind first:
    `. as $k | ($claimed | index($k))`. Same for `has()`.

47. **Register should treat HTTP 409 as "already exists" unconditionally.** Matching on the message
    text turns a re-seed into a hard failure the day someone rewords the string.

## 2026-09-08 — Gate B ruling: evidence contract architecture

Gate B (evidence completeness validation) has been ruled on by Danny. Full ruling: `docs/design/gate-b-evidence-contract-ruling.md`. Turk owns implementation of the declared-projection adapter across `config/copilot-tools.yaml`, `executor.py`, and the C# seam test in `authority-service.UnitTests`. Livingston owns fixture validation and measurement of the two-tool subset (`get_account`, `list_account_transactions`). Both gates (A + B) must pass before the co-signature feature can execute in production.

## 2026-09-09 — the guard shouted about the wrong thing

48. **My own principle, inverted, cost Brian a morning.** I built the propose-path probe to stop
    a fake success — writing approval rows straight into the store would put cards on screen
    while the pipeline stayed dead. It then produced a **fake failure**, which is the same defect
    class: *a signal that is not specific to the thing that was supposed to fail.* The probe
    inspected the RAW upstream response shape and predicted `evidence_incomplete`. Turk's declared
    `evidenceProjection` (`0e19c15`) reshapes both reads INSIDE the executor, so the raw shape has
    not needed to satisfy `EvidenceComplete` since that commit. The prediction outlived the defect,
    the seeder refused to seed, and a real operator read a false blocker as a real one. Proof the
    gate was open the whole time: `run_b3022efa254d4dcb` completed end to end through exactly the
    two tools I was failing, and Livingston then drove 42 more.

49. **A predictive guard has a shelf life; a driven one does not.** The rule I will apply from now
    on: *if a check can be performed by DOING the thing, doing it is the only honest form of the
    check.* The probe now logs in, opens a copilot session, starts a run, and reads the trace
    back. It cannot go stale against a fix, because it has no model of what should happen — it
    reports what did. The upgrade is not only in correctness: the failure output got **better**,
    because `run.error` carries the service's own `code` and `message` and `tool.failed` carries
    the upstream status. A real refusal beats a prediction of one as a diagnostic every time.

50. **Classify on the positive frame, and never let a consequence wear the cause's name.** Success
    is `approval.required`, not the absence of an error and not the terminal status field — a run
    that dies before emitting anything has no errors either. And when a read has already failed,
    every `run.error` after it is a CONSEQUENCE: my first cut labelled a downstream
    `evidence_unavailable` as `[GATE B]` while the real cause was a 403 two frames earlier. That
    is the identical defect at line level. `gate-b` now means only *the reads worked and the
    contract still refused*.

51. **`show` must not write, so it must not probe by default.** The only honest probe CREATES an
    approval. Rather than let a verb named `show` quietly write, probing is opt-in (`-- --probe`)
    and its absence is printed as an absence: "this run did not check; nothing above is evidence
    that the propose path is open." An unstated non-check reads exactly like a pass.

52. **Waiting for *anything* instead of the thing you need — the same defect, in the poll loop.**
    `collect_ai_subjects` broke when `length(all scored) >= min_required`. Scored records outlive
    the identities that produced them, so fifty orphans cleared the threshold instantly, the loop
    never waited for THIS run's transactions to be scored, and the run died three lines later at
    the ownership filter with "none belong to an account owned by a customer this run seeded" —
    a message that reads like a data-store problem and is really a wait that ended early. It now
    waits on the seeded-owned count, resolved once before the loop, and the two failure modes
    (nothing scored at all / nothing scored that is ours) say different things.

53. **When data has to be shaped so a defect does not show, the workaround has become the design.**
    I gave the banker four accounts because `get_account`/`GetAccountTransactions` were
    owner-scoped, and I filed that as lesson 44 — a service fact to design around. It was a
    service *defect*: `GetAccountTransactions` filtered by the CALLER's userId and answered `200
    []` for anyone else's account, a success asserting a falsehood. My data shape made it
    invisible. Per Danny's ruling §B6 the accounts now belong to Casey and Dana, the banker owns
    none, and the guard test asserts the old shape's **absence** — "so nothing can quietly fall
    back." Lesson 44 is hereby superseded, and the general form is worth more than the specific
    one: *a dataset that exists to keep a check green is evidence about the code, not about the
    data.*

54. **Preserve the shape, move the ownership.** The empty account, the near-threshold deposits and
    the three near-identical credits are not decoration — Livingston measured the supervisor
    reasoning about real ledger contents (it proceeded on an account that genuinely held three
    duplicate credits and held on one that did not). A reseed that "tidied" those away would have
    silently deleted the measurement's subject. The dataset now says so in `_accountComment`, and
    a guard asserts the deliberately-empty account still has both a zero balance and zero
    transactions.

55. **A dataset invariant that is only true by luck will not stay true.** With ownership moved,
    Casey nearly ended up with two Checking accounts — and `seed_accounts` claims "the first
    unclaimed account of this type" while `demo:show` re-derives the evidence subject by type
    alone. "Which account" would have silently depended on server ordering, differently per
    environment. Fixed by making each owner's account types unique AND asserting it, rather than
    by writing more clever matching code.

56. **Money on this wire is a decimal STRING, and the scale belongs to the policy.** A JSON number
    in a money position is refused `payload_not_canonicalizable` by the Canonicalizer before the
    request leaves banker-copilot-service. The probe amount is derived live from
    `balance_adjustment_dual_control_amount` and formatted at the scale the policy PUBLISHES
    (`"1000.00"` -> 2 decimals), with `LC_ALL=C` on the `printf` so a comma separator cannot be
    emitted into a money field. Deriving the scale is the difference between following the policy
    and restating it. It also has to land ABOVE the line: below it the action is L1 and the
    supervisor fan-out never runs, so the probe would prove less than it appears to.

**Environment limits (stated, not glossed):** `jq`, `curl`, `python3` and `bash` are present, so
`tests/demo/test-demo-dataset.sh` was actually run and passes, and every new guard was
tamper-tested (banker-owned account, probe reverted to shape inspection, duplicate account type
under one owner — each fails). The new probe was exercised end to end against a **mock copilot
API** across open / refused-read / evidence-refusal / non-evidence-refusal / silent-run /
session-401 / timeout, and the request body was captured to confirm `amount` goes out as
`"2500.00"`. What I could NOT verify: anything against the live cluster. I ran read-only checks
only (`/api/auth/login` exists, `/api/users/login` is 405, `/api/copilot/sessions` is 401) and
drove **no seed run and created no approval**, because that needs Brian's approval and the
banker-read fix is still in flight. Task 3 is therefore correct-by-ruling, not verified-by-run.
