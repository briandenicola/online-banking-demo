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

---

**2026-09-09 (Scribe)** — Inbox merge and deploy verification complete. Your 11 queued decisions from `.squad/decisions/inbox/` are now merged into the canonical ledger at `.squad/decisions.md`. Authority-service has deployed cleanly to `banking-demo` namespace with the §B3.2 startup guard active (`banker-copilot-authority`, policyVersion `pv1:d7b3db9f5ada15b8`, 22 thresholds, 13 action types).


---

## Learnings (2026-09-09 — empty-ledger seeder fix, `332-beta`)

57. **The endpoint I reach for by habit is not always the one whose entitlement I can prove.**
    The seeder read `GET /api/transactions/account/{id}` with a customer token to answer "have I
    already posted this?". That is a question about *my own rows*, and I was asking it through an
    *account-scoped* route. Turk's §B2.2 narrowing then made the mismatch visible: on a fresh
    reseed the ledger is empty, entitlement in that service is derived only from the returned
    rows, zero rows prove nothing, and the owner got `403` reading their own account. The fix was
    not to widen the service — it was to ask the question I could prove, via
    `GET /api/transactions/my`, which is scoped to the caller's `userId`. Four call sites, one
    read per identity, fewer HTTP calls than before. **The service was right; the caller was
    lazy.**

58. **Lesson 44 has a token-shaped variant, and Danny caught me before I could reach for it.**
    The cheapest fix was to pre-read with the banker token. That is not "using the right
    credential" — it is acquiring authority the caller does not have so a check stops firing. It
    would have made the seed pass while leaving `seed_transactions()` permanently unable to
    describe what a customer can actually do, and the next reader would have concluded, falsely,
    that seeding requires banker authority. `/my` is the opposite move: it does not borrow
    authority, it asks a question the caller's own token *is* the proof of.

59. **The dangerous half of this fix was the half that could not fail loudly.** The visible bug
    was a `403` with an exit status — the good kind of defect, it stopped the run and named
    itself. The fix's own failure mode was the opposite: a bare `.accountId` against a PascalCase
    body matches zero rows, so the idempotency check reports "not yet posted" every run and the
    reseed **double-posts every transaction**. Silent data corruption hiding inside the fix for
    the visible bug. `(.accountId // .AccountId)` everywhere, and I confined every transaction-row
    read to one helper so there is exactly one place for that trap to live — and one place to
    guard.

60. **A grep guard dies on reformatting; a behavioural guard does not.** I wrote both. The
    textual one asserts the paired form is present in `transactions_on_account()`; the
    behavioural one `eval`s the real helper out of `demo.sh` and feeds it a camelCase fixture and
    a PascalCase fixture, requiring one row from each. Tamper-tested: reverting the helper to a
    bare `.accountId` fails **both**. I also proved the whole idempotency decision offline —
    reseed/camel, reseed/pascal, empty ledger, same description on a different account, and a
    duplicate inside one run — all five decide correctly.

61. **When my own new guard fires on someone else's pre-existing code, scope the guard, do not
    widen the fix — and do not write an exclusion list either.** My first file-wide
    "no bare `.accountId`" check caught five lines in the AI-scoring path. Those read
    ai-service's `/api/admin/*` bodies — FastAPI, camelCase only, a different serialization
    contract, and not mine. Widening the fix would have sprawled the diff across another agent's
    area mid-flight; an exclusion list would have rotted. Narrowing the guard to the one helper
    that reads transaction-service rows was right *because* I had first made that helper the only
    such reader. **The guard was made narrow by making the code narrow, not by adding exceptions.**

62. **A verify pass that quietly changes what it counts is the worst possible place for an
    unlabelled meaning change** — it is the thing everything else is checked against. The
    per-account count now counts the *owner's* rows on that account, so the header reads
    `owner's transaction(s)`. Under single ownership those are the same set; joint accounts would
    make it an under-count, and saying so on the surface is what makes that discoverable rather
    than a future mystery. Same for `<prefix>TransactionCount`, which the model reads as evidence.
    Related trap I nearly shipped: `/my` returns rows across **all** of an owner's accounts, so
    counting the whole body once per account would have inflated every total silently. Filter,
    then count.

63. **Ruling 2 — a probe that drives a real path may NOT be idempotent (record only, no code).**
    I had asked whether repeated seeds leaving fresh probe approvals was a defect. Danny ruled it
    is correct behaviour. Reusing an outstanding approval turns *"is this path open **now**?"*
    into *"was it open **once**?"* — and that passes on precisely the day it should fail. A probe
    that asserts a live property must pay for that assertion every time; caching the answer
    retires the probe without anyone deciding to retire it. `e37e695` stands unchanged. This is
    lesson 44 again from a third angle: the cheap version passes, and passing is exactly what
    hides it. Full reasoning in
    `docs/design/probe-idempotency-and-divergence-silence-ruling.md`.

**Environment limits (stated, not glossed):** `bash -n` passes on `scripts/demo/demo.sh`;
`tests/demo/test-demo-dataset.sh` runs clean at **10 check groups passing**, and the new casing
guard was tamper-tested (both the textual and behavioural halves fail when the helper is reverted
to a bare `.accountId`). The idempotency decision was simulated offline across five cases. What I
did **NOT** do: no `task cloud:demo:reset`, no write of any kind to Azure, no `kubectl` mutation,
no commit, no branch operation, and no edit outside `scripts/demo/demo.sh` and
`tests/demo/test-demo-dataset.sh` — Turk and Linus were live in the tree. **The fix is therefore
verified statically and behaviourally, but not yet verified by a live reseed. Brian's run is the
proof.** No transaction-service redeploy is required; the running pods are correct.

---

**2026-09-09 (Scribe)** — Seeder fix merged to master. Four `demo.sh` call sites migrated from `GET /api/transactions/account/{id}` to `GET /api/transactions/my`, with PascalCase-tolerant filtering `(.accountId // .AccountId)`.

All three things that could have gone wrong quietly (PascalCase, inflated counts, duplicates) are guarded with two independent checks: textual (helper syntax) and behavioural (fixture-driven idempotency sim). Tamper-tested both; both fail on revert, both pass now.

**Brian's reseed unblocked.** Seeder now asks "what have I posted" through its own token's view instead of asking an account-scoped endpoint without entitlement on an empty ledger.

**No redeploy.** No Azure writes, no kubectl mutations. Live reseed is the remaining proof.


---

## Learnings (2026-09-09 — canonicalizer fractional payload, `332-beta`)

**The bug.** `config/demo-dataset.json` approval #11 (`l2-score-override-pending`) carried
`"newScore": 0.25` as a raw JSON float. `authority-policy.yaml` declares
`transaction.score.override.hashFields: [transactionId, newScore, rationale]`, so `newScore` is
projected and canonicalized. `Canonicalizer.WriteNumber` rejects `JTokenType.Float` outright.
HTTP 400 `payload_not_canonicalizable`. Fixed by changing the JSON **type** only —
`"newScore": "0.25"`. The semantic value is unchanged and stays in the `riskScore` 0.0–1.0
domain (`ai-service` clamps to `max(0.0, min(1.0, ...))`; `overrideScore` is `ge=0.0, le=1.0`).
Non-money strings are NFC-passed through unmodified, so `"0.25"` canonicalizes to exactly `0.25`.

**The real lesson — the literal is not what gets sent.** I nearly guarded the wrong thing.
`resolve_placeholders()` in `demo-lib.sh` substitutes `{"@threshold": n, "@delta": d}` with
**jq arithmetic**, `base + delta`, and it is the *result* that is POSTed. Eight approval
`payload.amount` fields are exactly this shape. They pass today only because every
`*_dual_control_amount` threshold and every delta happens to be integral. A money threshold
published as `1000.50` would make `tonumber` yield `1000.5` and every one of those eight
approvals would start failing at once. `seed_approvals` uses plain `resolve_placeholders` for
the payload — it does **not** call `money_from_threshold`, which is what the probe path uses to
render `"2500.00"`. That asymmetry is the latent defect; the guard now covers it.

**@delta is not inherently safe — it is out of scope, which is different.** The two fractional
`@delta` values (`agent.confidence -0.12`, `session.anomalyScore +0.05`) resolve to genuine
floats: `0.58` and `0.8500000000000001`. They survive only because they live under `facts`, and
`hashFields` names payload paths only, so they are never canonicalized. Move either one into a
`payload` and it breaks immediately. Path scope, not value safety. Do not record it as "floats
are fine in the dataset."

**Guard shape.** Rule is read out of `Canonicalizer.cs` (staleness assert on the float-rejection
site) and `moneyFields` out of the policy YAML. No hand-maintained list of "fields that must be
strings" — that is the fragile shape Danny flagged in the Go `publishedEventTypes` list. The
check resolves each payload the way the seeder does, then asserts every numeric leaf is integral.

**Tamper-tested twice**, per house rule: reverting `newScore` to `0.25` fails with the non-money
message; setting `approvals[0].payload.amount["@delta"] = -30.5` fails with the money message.
Both restored.

---

## Learnings (2026-09-09 — the seeder waits for what it will require, `332-beta`)

**The defect, in one line (Danny §R10).** *A seeder must wait for the thing it will later
require. Any predicate used to SELECT a subject must be the same predicate that TERMINATES
the wait.* The old `collect_ai_subjects` poll broke on `n_usable >= minScoredRequired` and
then chose a flagged subject on a property — `.amount >= dual-control line` — it had never
waited for. `flag-review-denied` therefore landed on L1 or L2 by luck, and nothing anywhere
asserted which.

**Why I made the predicate a named function.** `qualifying_flagged_pool()` is called from
the break condition *and* from the selection. Two inline `jq` expressions would have been
shorter and would have drifted apart on the first edit — which is the same class of bug one
level up. If the predicate is the fix, the predicate must be one object.

**jq sorts a string above every number.** `"9350" >= 25000` is `true`. Every `.amount`
comparison and every `sort_by` key in the new pool goes through `tonumber`. Without it the
guard would have passed its own tests and silently admitted below-the-line rows — a fix that
reads correct and does nothing. Case 7 of the termination proof exists for exactly this.

**A static guard narrower than the runtime it stands for will reject a correct design.**
Danny asked me to verify that declaring `escalator: large-flagged-amount` gets the runtime
assertion for free. It does — `PolicyEvaluator` puts action-local *rules* into the same
`firedEscalators` list as global escalators, tagged `action_rule`. But
`test-demo-dataset.sh` built its accepted set from `policy["escalators"]` only, so the static
check would have failed a declaration the runtime can prove. The instinct to reach for
`expectedRung` instead — i.e. to change the design to satisfy the test — was wrong, and the
advisor stopped me doing it. **Fix the guard's scope, not the design.**

**Proving a poll terminates is not something you reason about.** The single real risk in
this change was turning a 45s wait into a guaranteed 300s timeout. I extracted the shipping
`qualifying_flagged_pool()` and the shipping break expression out of `demo.sh` by text, and
drove them: qualifier on iteration 3 (terminates, picks the 61200 row where the old condition
would have taken 9350), qualifier never (runs out cleanly into the die), zero flagged rows,
`--allow-unescalated`, orphan-account rows, the `-amount`/`-riskScore` tie-break from both
input orders, string amounts, and the `gte` boundary at exactly 25000. Then a second harness
ran the **real `collect_ai_subjects`** against stubbed HTTP and exercised all four exit
branches. `--allow-unescalated` was **executed**, not just written.

**The opt-out is not the thing Danny rejected.** He rejected *silent* default variance.
A flag the operator types, that prints what is degraded and that the run is not
measurement-grade, is the opposite. `--allow-unescalated` deliberately does NOT become a
scoring opt-out: with zero flagged rows it still dies and points at `--allow-unscored`.

**Environment limits, stated.** `bash -n` clean; `tests/demo/test-demo-dataset.sh` 10 groups,
214 assertions, 0 failures; new converse guard tamper-tested (removing the `escalator`
declaration fails it with the intended message, restored). The first tamper attempt was
**invalid and I nearly recorded it as a pass** — the test resolves `demo.sh` relative to the
dataset's `parent.parent`, so a fixture in `/tmp` aborted on `FileNotFoundError` before ever
reaching my assertion. A red result is not evidence until you read *why* it is red. What I
did NOT do: no live reseed, no `task cloud:demo:reset`, no Azure or kubectl write, no commit.
**Brian's reseed remains the proof.**

## Durable guards (carried into future work)

### Guard (a): Flagged row lookup key is `.id`, not `.transactionId`

**Rule:** `.id` is the Redis lookup key for flagged transactions; `.transactionId` is NOT.

- `.id` = scoring-event UUID, minted per scoring event (`anomaly_service.py:879`). Use for **references**: payload fields, evidence API calls, anything a read tool resolves.
- `.transactionId` = the banking transaction id, carried on rows. Legitimate for **correlation** only.
- A read on `.id` returns 200 (or 404 if the row was purged). A read on `.transactionId` returns 404 even for rows that exist.

**Do NOT "fix" a seeder to use `.transactionId` even if it "looks more meaningful".** The error would not become visible until the read fails in production.

**Why it matters:** only **14 of 128** flagged rows carry a non-empty `.transactionId`. The 114 that don't cannot be identity-matched. A design that rests on this field is weaker than one that rests on `amount`/`accountId`, which fresh rows always populate.

### Guard (b): A seeder must wait for what it will later require

**Rule:** Any predicate used to **select** a subject must be the same predicate that **terminates** the wait.

**Failure mode:** Filtering on a property the poll did not wait for is a race with an assertion bolted onto the end. If the poll breaks on `n_usable >= 1` and the filter requires `.amount >= 25000`, you are racing the moment a second transaction scores against the moment its amount is computed. ~21 of 23 runs will fail.

**Implementation:** The same function must be called from both the break condition and from the selection. That is the whole point.

**Die distinction:** The `die` must name its cause. "nothing flagged at all" (stream/Foundry/FLAGGING_THRESHOLD problem) vs "flagged but nothing qualifies" (model scored low, or poll window too small) send debuggers to different services.

**Opt-out:** If the qualifying subject depends on a model score, a hard `die` on low-score days leaves the operator with no demo. An escape hatch with a typed flag (`--allow-unescalated` style) that degrades the run and prints what is degraded is legitimate. A *silent* default variance is not.

## Learnings (2026-09-09 — demo approval TTL env override, `332-beta`)

**Task:** Approvals expired ~20 min after seeding, killing the entire escalator queue before a
§7.1-§7.7 walkthrough could finish. Danny's ruling (§R12, *not* §R11 — §R11 is the `.id` lookup
guard; the brief mis-cited it) called for an environment-only TTL override. Brian approved 8h.

### A version hash that MOVES can be proof the change worked, not proof you broke something

The task carried a stop-condition: *"if the policy version hash changes, you altered policy
content — stop."* **That premise is false, and the source says so in as many words.**
`ResolvedPolicy.ComputeVersion` hashes the **resolved** threshold values, not the file:

> *"Replace the threshold DEFINITIONS with their RESOLVED VALUES. This is the whole point: the
> hash must move when `POLICY_TRANSFER_L2_AMOUNT` changes, even though the file did not."*

So an env override **must** move the hash. A hash that stayed at `pv1:d7b3db9f5ada15b8` would
have meant the override *silently failed*. The stop-condition, taken literally, would have made
me abort on the single strongest signal of success and keep going on failure — exactly inverted.

**Rule: before accepting a "if X changes, you broke it" tripwire, read what X is computed over.**
A tripwire is a hypothesis about a mechanism, and it inherits every error in that hypothesis.
Verify the invariant, not just the observation.

**The right invariant** was available and is what I actually reported: policy **identity** must
hold (`policyId`, 22 thresholds, 13 action types) and the *file* must be untouched
(`git diff config/authority-policy.yaml` empty), while the *resolved values* move. Identity
stable + values moved = correct. That distinction is the whole design.

### Verify the mechanism's limits, not just its existence

Danny verified the loader honours `POLICY_TTL_*` and he was right. But "the knob exists" does
not mean "your value fits". `ValidateThresholdValues` rejects a policy and **refuses to start**
the service on a bad threshold. I read it before deploying: `duration_seconds` requires a
non-negative integer and has **no upper bound**, so 28800 is safe. Had a cap existed, the
override would have crash-looped authority-service overnight, on the eve of the demo, from a
change everyone had signed off as trivially safe. Cost of checking: one file read.

### Two details the prescriptions got wrong, both found by enumerating from source

1. **The set was 9, not the 8 I was handed.** `ttl_loan_decision` was missing from the brief and
   from Danny's three-var suggestion. Enumerating `kind: duration_seconds` from the file gives 10;
   `retention_seconds` is 90-day record retention, not an approval clock, so it stays at default.
2. **The default TTL's env key is `POLICY_APPROVAL_TTL_SECONDS`, not `POLICY_TTL_DEFAULT`.**
   Pattern-matching the `POLICY_TTL_*` convention onto it would have produced a var that set
   nothing, with no error — the loader only rejects thresholds declaring *no* env key, it cannot
   detect an env var that matches nothing. **An unrecognised env var fails silently. Always read
   the `env:` key off the threshold rather than inferring it.**

### `:latest` + `imagePullPolicy: Always` makes "config-only" a claim you must prove

A `rollout restart` on a `:latest` tag re-pulls, so a restart intended as config-only can
silently swap the binary. I captured `.status.containerStatuses[].imageID` before and after:
identical `sha256:e71a449e…`. **That digest comparison is what makes "no rebuild happened" a
measurement instead of an intention.**

### Coverage that depends on a value someone else is about to change

Third instance in one ruling (§R3, §R12, this). Verification check **2.5** — TTL sweeper fires →
`denied` / `TTL_EXPIRED` — was only ever observable *because the TTL was short*. Nothing about it
was deleted or edited; it was disabled by a number changing somewhere else entirely. **Be precise
about what actually broke:** the sweeper still runs (`Approval__SweepIntervalSeconds: 60`,
untouched). What is lost is the **opportunity to observe it** — no demo-seeded approval now
reaches expiry inside a test window. Saying "the sweeper is disabled" would have sent Livingston
hunting a `BackgroundService` bug that does not exist.

### Deploy-path notes for this repo

- `deploy/flux/` describes a Flux Kustomization, but **Flux is not installed** on
  `model-osprey-55220-aks` (`kubectl get kustomizations` → no such resource type). Deployment is
  manual. Checked rather than assumed — had Flux been live, patching the cluster directly would
  have been reverted within its 10m reconcile and my verification would have expired with it.
- The standing ban on `kubectl apply -k deploy/kustomize/base` is well-founded: base carries
  literal `REPLACE_WITH_ACR_LOGIN_SERVER` / `REPLACE_WITH_TAG` placeholders and applying it
  straight would drive every deployment in the namespace to `ImagePullBackOff`.
- Non-secret env for every service flows through the shared `banking-demo-config` ConfigMap via
  `envFrom`. Only `authority-service` sets `POLICY_FILE_PATH`, so it is the sole policy loader —
  the added keys are inert in the other twelve pods.

---

## Learnings (2026-09-10 — shipping Linus's `/api/api` fix to AKS, `332-beta`)

Brian was blocked mid-walkthrough. Linus's fix was uncommitted in the working tree; my job was
to ship it, not edit it. Total elapsed: ~6 minutes.

### The reusable deploy sequence for ONE service

This is the whole loop. Write it down because I keep re-deriving it:

```bash
# 0. baseline FIRST — with :latest the tag never moves, so the digest is the only proof
kubectl get pods -n banking-demo -l app=ui-app \
  -o custom-columns='NAME:.metadata.name,START:.status.startTime,IMAGEID:.status.containerStatuses[*].imageID'
kubectl get configmap banking-demo-config -n banking-demo -o jsonpath='{.data.POLICY_APPROVAL_TTL_SECONDS}'

# 1. pre-flight compile (NOT the shipped artifact — the Dockerfile builds its own)
cd src/ui-app && CI=false npm run build

# 2. build + push. az acr build uploads the LOCAL DIR, so uncommitted changes ARE included.
task cloud:build:ui-app          # -> az acr build --registry $ACR --image ui-app:latest ./src/ui-app/

# 3. roll ONE deployment. Never `task cloud:deploy` for a single service.
kubectl rollout restart deployment/ui-app -n banking-demo
kubectl rollout status  deployment/ui-app -n banking-demo --timeout=300s

# 4. prove it: digest changed, and the served asset changed
kubectl get pods -n banking-demo -l app=ui-app -o custom-columns='...IMAGEID:...'
curl -s https://onlinebankingdemo.bjdazure.tech/ | grep -o '/static/js/main\.[a-z0-9]*\.js'
```

Run: ACR digest `sha256:aaee5e41…` → `sha256:6d92ae1e…`; served bundle
`main.b2660634.js` → `main.6e93dcd0.js`, byte-identical hash to my local pre-flight build,
which is a free extra proof that the image carries the tree I compiled.

### `task cloud:deploy` is the wrong tool for a one-service fix

Its last step is `kubectl rollout restart deployment -n banking-demo` — **every** deployment —
and it re-runs `_configmap:apply`, which streams values out of Terraform state. On a demo day
with a live env override in `deploy/kustomize/base/configmap.yaml`, that is the one path that
can silently revert it. `cloud:build:<svc>` + a targeted `rollout restart` touches exactly one
workload.

### Establish the negative control BEFORE you overwrite the evidence

I nearly grepped the new bundle for `/api/api` and called it proof. The old bundle contained
**zero** occurrences of `/api/api` — the doubling happened at *runtime*, from axios
`baseURL: '/api'` concatenated with an absolute path from config. Grepping for the symptom
would have "passed" against the broken build too.

What actually works: grep for **strings unique to the fix**. Confirmed absent from the old
bundle, present in the new:

| marker | old `b2660634` | new `6e93dcd0` |
|---|---|---|
| `does not start with the client baseURL` | 0 | 1 |
| `the request did not reach authority-service` | 0 | 1 |

**Generalisation: a runtime-composed bug leaves no literal in the artifact. Grep for the fix's
fingerprint, not the bug's symptom — and verify the fingerprint is absent from the artifact you
are replacing, or the check proves nothing.**

### The strongest evidence was a four-line curl, from outside

```
POST /api/api/copilot/sessions      -> 405 text/html          (nginx refuses; SPA fallback)
GET  /api/api/authority/approvals   -> 200 text/html          <-- the silent killer
POST /api/copilot/sessions          -> 401 application/json   (reached the service)
GET  /api/authority/approvals       -> 401
```

That 200 + `text/html` is the whole defect in one line: the SPA history fallback answers any
unmatched GET with `index.html` and a success code, so `response.data.items` is `undefined` and
an empty list renders over a full queue. **A 200 whose `content-type` is `text/html` from a JSON
API is a routing failure wearing a success code.** Assert on content-type, not just status.

### Someone else deployed into the same namespace while I was building

All 13 other pods restarted at 18:32:58-18:33:01Z (annotation `restartedAt 2026-09-10T13:32:57-05:00`)
— a namespace-wide `task cloud:deploy` by another agent, concurrent with my ACR build. My ui-app
pod is 18:34:24Z. I only knew this was not my doing because I had timestamped the baseline before
starting; otherwise I would have spent ten minutes proving a negative.

Two real hazards it created, both checked rather than assumed:
1. That restart re-pulled `ui-app:latest` at 18:32:58 — **before** my push finished at 18:34:15.
   Had I skipped step 3 and trusted the ambient restart, the pod would have run the OLD image
   with a fresh timestamp. Timing alone would have looked convincing.
2. It re-applied the ConfigMap. Verified the override survived **in the running process**, not
   just in the ConfigMap object: `kubectl exec deployment/authority-service -- printenv
   POLICY_APPROVAL_TTL_SECONDS` → `28800`, and the pod logged `pv1:6b4dec9a0d13aa4b`, the
   overridden hash. A ConfigMap read alone would not have proven the pod ingested it.

**Baseline everything you will later claim to have changed, with timestamps, before you act. In
a shared namespace you cannot distinguish your effect from someone else's after the fact.**

### Approvals survive pod restarts

Brian's 10 seeded approvals are in Cosmos, not pod memory. The full-namespace restart did not
touch them; the expiry sweeper came back clean (`interval 00:01:00, batch 100`). Worth stating
plainly because "everything restarted" reads like "the fixtures are gone" and it is not true.

### Note for whoever runs the walkthrough

Deployed `runtime-config.js` still has `bankerCopilot: false`, so `/copilot` needs the `?ff=`
override or a localStorage toggle. Unchanged by this deploy, and Brian already had it on.

### Addendum (same day) — timing check: did the build catch Linus's *final* writes?

Brian flagged that Linus was still writing when I was spawned. Resolved by measurement, not by
arithmetic on wall-clock times.

**mtimes of the last three files Linus touched** — the newest file anywhere under
`src/ui-app/src` is `describeHttpFailure.test.ts` at **13:29:02**. My local pre-flight build ran
at 13:32 and the ACR build at 13:32-13:34, so every write preceded both. Nothing under
`src/ui-app/src` is newer than 13:29:02, which is the check that matters — a single file mtime
answers "did this one land", `find -newermt` answers "did anything land after me".

**The canary Brian asked for came back clean but nearly misled me.** Two greps on the served
`main.6e93dcd0.js`:

- `It is not running on the server` (the old hardcoded harness error) → **0**. Correct.
- `describeHttpFailure` (the new function) → **0**. *Also* zero — and that proves nothing.

**Minification mangles local identifiers; it preserves string literals.** Grepping a production
bundle for a function name is a test that fails on a correct build. Had I stopped at that line I
would have rebuilt a perfectly good image, or worse, reported a stale deploy. The absence of the
old string is real evidence because it *is* a string; the absence of the symbol is an artefact of
the toolchain.

What actually proved the second fix shipped — four string literals from `errors.ts` /
`CopilotContext.tsx`, all present in the live bundle, all confirmed **absent from `git show
HEAD:`** so the marker is genuinely new:

| marker | HEAD | live bundle |
|---|---|---|
| `The endpoint URL looks wrong rather than the service being down` | 0 | 1 |
| `Your session may have expired` | 0 | 1 |
| `The harness request` | 0 | 1 |
| `copilot: intent submission failed (status=` | 0 | 1 |

**Rule: to verify a minified bundle, grep for user-visible string literals, never for identifiers.
Pair every "new string is present" with "old string is absent" and confirm both against the
artifact you replaced.**

One loose end worth naming so nobody trips on it: `It is not running on the server` still appears
once in the tree, in `__tests__/describeHttpFailure.test.ts` — the test asserting the string is
gone. Test files are not in the production bundle, so this does not contaminate the canary, but a
naive `grep -r` across `src/` will report a hit and look like a stale build.

File set shipped matches Linus's expected list exactly: 5 modified sources + 6 new test files.
No rebuild required.

---

## Learnings (2026-09-10 — SSE stream withholds headers for 15s; layer verdict, `332-beta`)

Brian's approval card refused to enable Sign: "Live updates are interrupted… Reconnecting."
Reported as an SSE stream that never opens. **Verdict: application, not ingress.** Not mine.
Not patched — reported to Turk.

### The hypothesis I was handed was wrong, and my own charter is what made it plausible

My charter says "nginx gateway — SSE requires `proxy_buffering off`", so the natural read was a
buffering proxy. **There is no nginx in the cloud request path at all.** `src/ui-app/nginx.conf`
serves the SPA only; `infra/local/gateway.nginx.conf` is docker-compose. In AKS it is Istio:
`banking-demo-vs` VirtualService → `banker-copilot-service`, `/api/copilot/` prefix,
`timeout: 3600s`. **A charter note about the local topology nearly sent me to reconfigure a
component that is not deployed.** Check which proxy is actually in the path before tuning one.

### Three measurements, escalating, each cheaper than the next step

1. **Unauthenticated request through the public URL** — no token needed, and it settled the layer
   in one call: `401` in 0.55s with `x-envoy-upstream-service-time: 17`. Envoy flushes headers
   fine. Whatever hangs, hangs *after* auth, inside the app.
2. **Authenticated, with a window wider than the suspected timeout** — `time_starttransfer=15.55s`,
   `HTTP 200`, `content-type: text/event-stream`, and decisively
   **`x-envoy-upstream-service-time: 15030`**. That header is Envoy timing the *upstream*. It is
   the proxy testifying that the delay was not the proxy.
3. **`kubectl port-forward` to pod:8005, Envoy entirely removed** — `time_starttransfer=15.51s`,
   `server: uvicorn`. Identical. Ingress exonerated beyond argument.

**`x-envoy-upstream-service-time` is the cheapest proxy-vs-app discriminator in this cluster and I
should reach for it first.** The port-forward confirmed what it already said, for ~50ms of doubt.

Note the service port is **8005**, not 8000 — my first port-forward failed with `connection
refused` inside the netns. Read `.spec.template.spec.containers[*].ports[*].containerPort`;
guessing the port costs a round trip.

### The cause, in Turk's file

`src/banker-copilot-service/app/routes/sessions.py:353`, inside `stream_session`:

```python
if stream is None:
    stream = await runs.await_next_run(session_id, timeout=heartbeat_seconds)
```

This `await` sits **before** the `StreamingResponse` is returned. Starlette cannot emit
`http.response.start` until the handler returns, so attaching to a session with no active run —
the normal UI order, and exactly Brian's case — withholds the status line for a full heartbeat
interval. The generator `_events()` already handles the no-run case correctly with heartbeats;
the pre-flight await duplicates that work in the one place where it costs the response headers.
**The fix is to let `_events()` do it: drop the pre-flight await so the first heartbeat yields
immediately.** The code even documents the intent — "open the stream anyway and let the
heartbeats carry it" — the ordering just defeats it.

`COPILOT_SSE_HEARTBEAT_SECONDS=15` in `banking-demo-config`, confirmed as `15` inside the pod.
15 × 1s = the 15.03s Envoy measured. The number matched the knob exactly, which is what turned a
plausible story into a diagnosis.

### Why the reporter saw a hard hang and I saw a slow 200

They ran `--max-time 15`. First byte lands at **15.51s**. They timed out 0.5 seconds under the
boundary, so curl exited 28 having received zero headers — indistinguishable from a dead socket.
**A timeout set near the value you are trying to measure reports absence instead of latency.**
When a stream "never opens", re-run with a window several times wider before believing it. One
flag turned a 15-second delay into a phantom outage and sent the diagnosis at the wrong layer.

### Why I did not just lower the knob, though it is mine to lower

Tempting: it is config, it is in my ConfigMap, Brian is blocked, one restart. I held, for reasons
that are worth keeping:

- `heartbeat_seconds` is **overloaded** — it is also the queue poll timeout *and* the increment in
  `waited += heartbeat_seconds` against the 3600s idle budget. At 2s every open stream emits ~1800
  heartbeat frames instead of ~240. Whether Linus's client reads that cadence as healthy or as
  churn is untested, and I cannot test it without driving Brian's UI.
- **I do not know the gate's predicate.** The card says "cannot verify this is still the current
  payload", which may require a payload-hash event rather than merely open headers. Shortening
  time-to-headers to 2s could leave the button greyed anyway.

**Do not ship a change whose success criterion you cannot evaluate.** Tuning a shared constant to
mask a sequencing bug trades a 15s symptom for an untested cadence and leaves the cause in place.
Offer it as a stopgap someone else authorises; do not quietly apply it and call it fixed.

### Housekeeping

Probe sessions `sess_2c322a144c324ac9` (mine) created **no runs and no approvals**. Brian's 10
seeded approvals untouched; `POLICY_APPROVAL_TTL_SECONDS` re-verified **28800** in-process after
all of this. Port-forwards cleaned up.

One trap while cleaning up: `pgrep -f "port-forward -n banking-demo"` **matches its own command
line**, so it reported a fresh PID after every kill and looked like a respawning process. `ps -eo
pid,cmd | grep kubectl` showed the truth — nothing running. A self-matching pattern is a fake
infinite loop.

### Addendum — was the SSE fault new, and who deployed? (2026-09-10)

Asked to test whether the unattributed 18:32:57Z full-namespace deploy *caused* the SSE outage.
Answer: **the defect is pre-existing; the deploy is what made it visible.** Both halves matter and
collapsing them either way is wrong.

**Pre-existing, three independent ways:**
- `git blame` puts the blocking await at commit `bcfd8b9`, **2026-09-04** — six days old.
- The running image digest `d3eb82f4…` was pushed **2026-09-09T12:00:28Z**, yesterday. Only two
  ACR runs happened today (`dt29`, `dt2a`) and **both built `ui-app`**. No copilot image was built
  today; the deploy restarted the pod onto the same binary.
- The pod came back clean: `READY=true`, `RESTARTS=0`, zero errors or tracebacks in the whole log.

**But the deploy is not innocent, and this is the part I nearly missed.** `RunStreamRegistry` is
constructed in `lifespan.py` and its own docstring says *"In-process registry of live runs.
Durability lives in the sink, not here."* — `self._runs: dict[str, RunStream]`, per process. The
18:32:59 restart **destroyed every in-flight run stream.** A browser attached to a live run lost it
permanently; on reconnect `latest_for_session` returns `None`, which routes straight into the
`await runs.await_next_run(...)` path and the 15s of no headers. Brian's banner at ~18:35 is two
minutes after the restart because **the restart converted a latent ordering defect into a visible
outage.** "Pre-existing" and "triggered by the deploy" are both true.

**Generalisation: "was it already broken?" and "did the deploy break it?" are different questions.
A latent defect on a cold path plus a restart that forces everyone onto that cold path produces an
outage that is genuinely new while the code is genuinely old.**

**I raised a false alarm mid-investigation and want it recorded.** The log showed
`GET /api/copilot/stream → 404` and `GET /api/copilot/approvals/stream → 404`, and I flagged it as
"a second fault, this changes the diagnosis". It did not. Neither string appears anywhere in the
repo, in `src/ui-app/src/`, or in the deployed bundle — they were manual URL guesses from whoever
probed before me. **Before escalating a suspicious request path found in a server log, grep the
client for it. A 404 in an access log proves someone asked; it does not prove your software asked.**

The genuinely useful log check was the reporter's own suggestion: whether the connection appears at
all. It does — my probes logged as `200 OK` after the client gave up — which independently confirms
the request reaches the app and the app owns the delay.

### Attribution: it was Brian's own interactive shell, not a pipeline

`~/.zsh_history` carries epoch timestamps and durations:

```
1789064972:152;task cloud:build:ui-app   -> 2026-09-10 18:29:32Z, ran 152s
1789065133:0;task cloud:deploy           -> 2026-09-10 18:32:13Z
```

That lines up exactly: ACR QuickRun `dt29` started 18:29:41Z and built **ui-app** digest
`b1c0f189…`; `cloud:deploy` then stamped `restartedAt 2026-09-10T13:32:57-05:00`. Someone was
shipping the same ui-app fix in parallel with me and superseded nothing — my `dt2a` build
(`6d92ae1e…`) landed after and is what runs now.

**Not CI.** There is **no deploy workflow** in `.github/workflows/` at all (build-and-test,
mutation-testing, preview-sdk-pin-guard, squad-*, dependabot only), and the most recent Actions run
was 12:06Z. Corroborating: the `restartedAt` offset is **`-05:00`**, i.e. the kubectl client was in
CDT — a GitHub-hosted runner would have stamped UTC.

**Three attribution signals worth reusing, cheapest first:** the `restartedAt` timezone offset
(local vs runner), `az acr task list-runs` with `--run-id` to see *which image* each run produced,
and `~/.zsh_history` epoch:duration pairs. My own commands never appear in zsh history because this
tool runs non-interactive bash — useful to know when reading that file as evidence, in both
directions.

### The feature flag cannot affect the stream

`bankerCopilot` is read only by `featureFlags.ts`, `App.tsx`, `AppShell.tsx` and
`FeatureFlagPanel.tsx` — mount and nav. `copilotStream.ts` builds its URL from
`getCopilotConfig().endpoints.sessionStream`, which never consults a flag. The `?ff=` override
decides whether the surface renders, not how it connects. Ruled out.

### Addendum — the control case that isolates the await, and a log heuristic that is wrong here

**The single cleanest piece of evidence, found last and worth the most.** Same endpoint, same
token, same session, same ingress — only one variable changed, whether execution reaches the
`await`:

```
GET /sessions/{sid}/stream                       -> 15.51s, 200
GET /sessions/{sid}/stream?runId=run_doesnotexist ->  0.77s, 404
```

`?runId=` routes into `raise HTTPException(404)` at line 346, *before* line 353. The handler,
auth, Envoy and TLS are all held constant and it answers in under a second. **A control case that
differs by exactly one branch converts "the app is slow" into "line 353 is the cause."** My own
history says a control case is the only thing standing between a plausible story and a wrong
decision; this is the third time it has paid.

**A proposed diagnostic that would have sent me back to the ingress.** The brief said: *"whether the
probe connections appear in the logs is itself diagnostic — if the service never logs the
connection, the request is dying in front of it."* Their authenticated probes appear **nowhere** in
the log (`sess_68f79e6874c04a7d`: 0 hits; the single `sess_1d8f4c6eba5e4b50` line is a **401**, which
was my own *unauthenticated* probe, not theirs). By that rule the verdict would be "dying in front
of the service" ⇒ ingress ⇒ mine.

That rule is wrong here. **uvicorn writes its access line when the response completes, not when the
request is accepted.** Their curl aborted at `--max-time 15`, half a second before the first byte at
15.51s, so no response line ever existed to log. Their 404 probes logged because those returned
instantly. Absence of an access-log entry for an aborted long-poll is expected, not diagnostic.

**Generalisation: an access log records completions, so it cannot testify about requests still in
flight. Use it to prove presence, never absence.** What actually proves the request reached the app
is `x-envoy-upstream-service-time: 15030` and the port-forward reproducing the delay with Envoy
gone.

**Not evidence, and I did not use it:** a green seeder run proves nothing about SSE — the seeder
polls `/api/copilot/runs/{id}/trace`, a plain GET. Flagged in the brief and correct.

**What I deliberately did not run:** starting a real run would have demonstrated the fast path
directly, but the planner can propose an approval, and Brian's 10 seeded approvals are his only
fixtures. The `?runId=` control gives the same isolation with zero writes. **Prefer the
side-effect-free control over the realistic one when someone else's fixtures are on the line.**

Restart health, re-confirmed for the record: `READY=true`, `RESTARTS=0`, started 18:32:59Z, no
errors or tracebacks in the log. **The service did not come back degraded** — the tempting simple
explanation is false.

---

## Learnings (2026-09-10 — deploying Turk's SSE fix, `bd01a1b`, `332-beta`)

The fix I diagnosed, shipped and verified. **15.55s → 0.56s time-to-first-byte**;
`x-envoy-upstream-service-time` **15030 → ~32**. Same curl, same session shape (no active run),
same ingress. Acceptance met.

```
task cloud:build:banker-copilot-service
kubectl rollout restart deployment/banker-copilot-service -n banking-demo
kubectl rollout status  deployment/banker-copilot-service -n banking-demo --timeout=300s
```

Headers now: `200`, `content-type: text/event-stream`, `x-accel-buffering: no`, first frame
`event: heartbeat` — all inside 0.6s. Four independent samples (0.62 / 0.59 / 0.50 / 0.52 / 0.56s),
because a single timing datapoint is an anecdote when the thing you are measuring is latency.

### Two agents built the same image three seconds apart, and mine lost

This is the concrete instance of the race I wrote up this morning as a hypothetical.

| run | started | finished | digest |
|---|---|---|---|
| `dt2b` (mine) | 19:10:10 | 19:11:03 | `30f06f55…` |
| `dt2c` (Brian's) | 19:10:13 | **19:11:12** | `0aea3595…` |

Both push `:latest`. **Brian's finished last, so `:latest` moved to his digest**, and my
`rollout restart` at 19:11:12 pulled *his* image. The running pod is `0aea3595…` — not the digest
my own build produced.

I only noticed because I compared the pod's `imageID` against the digest my build *reported*, not
merely against the previous digest. **"The digest changed" is not "my image is running."** The
weaker check passes here and would have let me claim provenance I did not have. Both builds came
from the same commit and the behavioural test passes, so the outcome is correct — but the claim
I could honestly make was narrower than the one I nearly made.

**Rule: with a mutable tag, record the digest your build emitted and assert the pod matches *that*.
If it does not, find out whose image you are running before reporting success.**

### The verification failed for a reason that had nothing to do with the fix

Mid-verification, three consecutive probes returned `http=000` and `ttfb=0`. The instinct is to
suspect the thing just deployed. It was not: **Brian had launched another full-namespace
`cloud:deploy` at 19:13:12Z** and every deployment was mid-rollout — 4 pods not ready, `/api/auth/login`
itself returning `000`. The site root still answered `200`, just slowly (5.8s).

I resisted debugging the SSE path and instead checked whether the *platform* was up. `kubectl get
pods` showed the answer in one call. **When a verification that passed 90 seconds ago starts
failing at a different layer than the change, check the environment before re-litigating the fix.**
Waiting ~40s for the rollout to settle and re-running produced three clean samples.

That churn also re-rolled `banker-copilot-service` onto a fresh pod (`6cccd4d755-f2mdr`), which is
an unplanned bonus datapoint: **the fix survives an independent redeploy**, still `0aea3595…`, still
sub-second. Verifying after someone else's deploy is stronger evidence than verifying after my own.

### What I confirmed did not move

`POLICY_APPROVAL_TTL_SECONDS` = **28800**, read in-process from the *new* authority pod after
Brian's redeploy — the override survived two full-namespace deploys today.
`COPILOT_SSE_HEARTBEAT_SECONDS` = **15**, untouched, which was the point: the fix is a code
ordering change, not a threshold tuned to hide a symptom. Zero errors in the copilot log,
`RESTARTS=0`.

No approvals created, signed or denied. No runs started — throwaway sessions only, exactly as
before, because the planner can propose approvals and Brian's fixtures are the afternoon.


### 2026-09-10 — Platform Analysis Session (#332)

**Session Type:** Infrastructure diagnostics and platform coordination
**Branch:** `332-beta`
**Outcome:** SSE layer identified, deployment coordination guidance documented, root cause traced

**Rusty's Contributions:**
- Diagnosed SSE header stall: blocking await in `stream_session`, not Istio/Envoy
- Provided evidence (x-envoy-upstream-service-time, port-forward control)
- Identified single-service redeploy path as preferred over full `cloud:deploy`
- Traced unattributed 18:32:57Z restart to local `task cloud:deploy` in Brian's shell
- Documented deployment coordination guards for walkthrough period

**Manifest:**
- `rusty-sse-headers-withheld-service-layer.md`: SSE diagnostic (merged to decisions.md)
- `rusty-single-service-redeploy-path.md`: Deployment governance proposal (merged to decisions.md)
- `rusty-unattributed-deploy-attribution.md`: Root-cause analysis (merged to decisions.md)

**Implementation:** Turk implemented SSE ordering fix per Rusty's recommendation; deployment model remains proposed

**Orchestration Log:** None (platform-only, no implementation artifacts)
**Session Log:** `.squad/log/2026-09-10T20:47:00Z-copilot-ui-and-authority-fixes.md`
