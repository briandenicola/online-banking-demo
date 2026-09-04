# Authority Service

The approval authority for Banker Copilot (epic #332). It is the **only** component that may
decide how much human sign-off an agent-proposed action needs, and the **only** component that
may write an approval record.

## Purpose

An AI agent proposes; a human approves; this service decides *which* human, *how many*, and
whether the approval is still valid at the moment of execution. It owns three things:

1. **The policy engine** — a declarative policy file maps `action + payload + actor + context`
   to a required rung (L1/L2/L3), a signer count, and a plain-English list of which escalators
   fired and why.
2. **The approval store** — the lifecycle `proposed → pending → signed → executed`, with
   `denied` as the single terminal rejection state.
3. **The execution gate** — nothing reaches a downstream service without being re-evaluated
   against the *current* policy first.

## Technology Stack

- .NET 10 (C#), ASP.NET Core Web API
- Azure Cosmos DB (Entra RBAC; in-memory repository for local dev)
- Redis Streams for audit events
- JWT bearer authentication
- OpenTelemetry via the shared `Observability` project

## Non-negotiables

These are enforced structurally, not by convention:

- **Zero hardcoded thresholds.** No dollar amount, count, CIDR, or IP appears in the code. Every
  magnitude comparison in the policy file must *name* a threshold; the loader rejects the policy
  at startup if one carries a bare number.
- **Fail closed.** A missing, unparseable, or invalid policy file is a startup crash. There is no
  "default policy" to fall back to, because falling back would mean approving things by accident.
- **Expiry means denied.** The sweeper writes `denied` + `TTL_EXPIRED`. Nothing is ever
  auto-approved by the passage of time.
- **Escalators cannot lower a rung.** The only combinator is `max` over an ordered rung set, so
  no combination of rules can produce a *weaker* requirement than the baseline. A property-based
  test asserts this over random escalator subsets.
- **Separation of duties is server-side, and is a set-membership test.** The L2 co-signer slot
  carries `mustDifferFrom: [<requester>]` — it names the excluded identity rather than counting
  distinct heads, because a tally is satisfied by arithmetic and a miscount passes silently.
  Hiding the button in the UI is not a control.
- **One copy per document.** No field on an approval restates another: `policy.policyVersion`
  appears exactly once, and there is no per-slot or per-execution copy of it. A schema contract
  test compares the document the service actually writes against the design doc's canonical set
  of field paths, because a Cosmos path mismatch returns zero rows rather than an error.
- **One write path.** Every mutation goes through `ApprovalRepositoryBase`, which runs the state
  machine guard first. Subclasses supply persistence only; there is no `SaveAsync(approval)` that
  would let a caller invent a transition.

## Rungs

| Rung | Signers | Who | Proposable by the agent |
|------|---------|-----|-------------------------|
| L1 | 1 | banker, supervisor, admin | yes |
| L2 | 2, second slot excludes the requester | banker + supervisor/admin co-signer | yes |
| L3 | 2 admins | admin only | **no** — out of harness, do it in the admin console |

## API

All routes are under `/api/authority` and require a bearer token.

| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/approvals` | Propose an action. Returns the evaluated rung and the fired escalators. Rejected if evidence is incomplete or the rung is L3. |
| `GET` | `/approvals` | List approvals, filterable by status/actor/target. |
| `GET` | `/approvals/{id}` | Fetch one, with its full explanation and signature slots. |
| `POST` | `/approvals/{id}/sign` | Add a signature. Enforces role, seniority, and separation of duties. |
| `POST` | `/approvals/{id}/deny` | Deny with a mandatory validated reason → `denied` + `HUMAN_DENIED`. |
| `POST` | `/approvals/{id}/execute` | Re-evaluate under current policy, then call the downstream service. |
| `POST` | `/policy/evaluate` | Dry-run the evaluator without creating an approval. |
| `GET` | `/policy` | The resolved policy summary and its `policyVersion`. |
| `GET` | `/healthz`, `/readyz` | Liveness; readiness reports the loaded `policyVersion`. |

## policyVersion

`policyVersion` is `pv1:` plus a truncated SHA-256 of the **resolved** policy — after environment
overrides are applied — not of the file bytes. Two pods given different threshold overrides are
running different rulesets, and the version must say so. `metadata.effectiveFrom` and
`metadata.owner` are excluded so that editorial changes do not invalidate outstanding approvals.

## The execution gate (epic §5.3.2)

At execution the service does two different things with two different policies, and the split
matters:

- The **payload hash** is recomputed under the `policyVersion` **stored on the approval**. The
  hash fields, money fields, and currency scale are frozen onto the document at propose time, so
  a later policy edit can never make a validly signed payload look tampered with.
- The **rung** is re-derived under the **live** policy.

If the live rung is *higher*, the approval is voided: `denied` + `POLICY_RUNG_ESCALATED`, linked
to its replacement by `supersededByApprovalId`. If it is unchanged or lower, the approval is
honoured — the service never auto-downgrades a requirement a human already met. A downstream
failure leaves the approval `signed` with `execution.state = failed`; there is no
`execution_failed` status.

## Payload hashing

RFC 8785 (JCS) canonicalization over the action's declared `hashFields`, with money rendered as
decimal strings at the policy's currency scale and `policyVersion` included in the hash input. A
declared hash field that is absent from the payload is refused, not hashed as empty — otherwise
"no amount" and "zero amount" would look identical to a signer. A signature binds actor identity,
payload hash, timestamp, and nonce.

## Configuration

| Key | Meaning |
|-----|---------|
| `POLICY_FILE_PATH` | Path to the policy YAML. Baked into the image at `/app/config/authority-policy.yaml`; mount over it to change the ladder without a rebuild. |
| `Approval__SigningKey` | HMAC key for approval signatures. **Must differ from `Jwt__Key`** — the service refuses to start otherwise, so a leaked bearer token cannot forge a signature. |
| `Approval__SweepIntervalSeconds`, `Approval__SweepBatchSize`, `Approval__RetentionSeconds` | Expiry sweeper. |
| `Denial__Reason*` | Denial reason quality bounds (min length, max length, distinct characters, repeated-unit detection, minimum letters). |
| `POLICY_*` | Per-threshold overrides. Every threshold named in the policy file can be overridden by env var; the override changes the `policyVersion`. |
| `UseInMemoryDatabase` | `true` for local dev; Cosmos otherwise. |
| `CosmosDb__ApprovalsContainerName` | Container name — configuration, never a literal in code. |

Redis and Cosmos follow the repo's dual-mode pattern: `AZURE_CLIENT_ID` present → Entra ID
(workload identity), absent → local connection string.

## Running locally

```bash
docker compose up authority-service        # port 6010

# or directly
cd src/authority-service
UseInMemoryDatabase=true \
Approval__SigningKey=LocalDevAuthorityApprovalSigningKey-NotTheJwtKey \
dotnet run
```

```bash
cd src/authority-service.UnitTests && dotnet test
```

## Audit events

Published to Redis Streams with PascalCase names matching the existing `event-processor`
convention: `ApprovalProposed`, `ApprovalSigned`, `ApprovalDenied`, `ApprovalExecuted`,
`ApprovalExpired`, `ApprovalSuperseded`, `ApprovalVoidedByPolicy`, and the policy events.
`ApprovalExpired` is retained as an event name even though expiry now resolves to `denied` — the
stream is append-only, so the event says what happened and `terminalReason` says what it means.
