# Banker Copilot — Frontend Design Spike

**Author:** Linus (Frontend Dev)
**Status:** Design spike — feeds Danny's epic spec. No implementation.
**Date:** 2026-09-04
**Scope:** `src/ui-app/` only. Backend policy engine is Turk's. Architecture-level calls defer to Danny.

**Input directives honoured:**
- `.squad/decisions/inbox/copilot-directive-banker-copilot-epic.md`
- `.squad/decisions/inbox/copilot-directive-banker-copilot-authority-model.md`
- `.squad/decisions/inbox/copilot-directive-banker-copilot-scope-boundary.md`

---

## 0. Framing — what we are actually building

This is **not a chatbot**. We already have one (`src/ui-app/src/pages/Chat.tsx`) and it is
deliberately *not* the model for this. A chatbot's product is the transcript. Here the
transcript is exhaust. The product is:

1. **A queue of work** the banker owes a decision on.
2. **A live trace** showing the agent reasoning, calling tools, and fanning out subagents.
3. **An artifact** — a memo, a decision packet, a proposed action — that the trace produced.
4. **A signature** — the human act that makes anything actually happen.

Design test I will apply to every screen: *if you removed the text input entirely, would the
surface still be usable?* The answer must be **yes**. The input box is a command bar, not the
product. A banker with a full queue may go a whole shift without typing anything — they work
the queue, read traces, and sign.

Second design test: **agents never approve.** Every affordance that could be mistaken for the
agent executing something must be visually and linguistically demoted to a *proposal*. The
verbs in this UI are `propose`, `recommend`, `gather`, `flag`. The only verbs that change the
world are `Sign` and `Deny`, and only a human can press them.

### 0.1 Vocabulary (used consistently in code and UI copy)

| Term | Meaning |
|---|---|
| **Run** | One agent invocation from intent to terminal state. Has an id, a plan, a trace, zero-or-more artifacts. |
| **Task** | A queue item. May be agent-initiated (something needs review) or banker-initiated (a typed intent). A task owns 0..n runs. |
| **Plan step** | A node in the agent's plan. Mutable — the agent re-plans. |
| **Tool call** | A leaf invocation against an allowlisted capability. |
| **Subagent** | A nested run spawned by the primary agent (e.g. an underwriting specialist, or the L2 supervisor agent). |
| **Artifact** | A durable output: memo, decision packet, comparison table, proposed payload. |
| **Approval request** | A durable object: `proposed → pending → signed → executed`, with `denied` the single terminal rejection state. Carries a payload hash and, when denied, a mandatory `terminalReason`. |
| **Rung** | L1 / L2 / L3 authority level required. |
| **Escalator** | A named reason a rung went up. Never down. |

---

## 1. Layout & Information Architecture

### 1.1 The harness surface

New route: **`/copilot`** (admin/banker-gated, same `isAdmin` guard pattern as `/admin` in
`App.tsx`). Full-bleed — this surface **opts out of the `Container maxWidth="lg"`** wrapper in
`AppShell`. Three panes need horizontal room; boxing it to `lg` kills the design. See §1.4 for
how to do that without forking the shell.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ SecureBank   Dashboard Accounts Transfers …            [Banker Copilot]  [Classic Admin] ●│  AppShell AppBar
├───────────────────────┬──────────────────────────────────┬───────────────────────────────┤
│ TASK QUEUE            │ PLAN / TRACE                     │ ARTIFACT CANVAS               │
│ (280–340px, fixed)    │ (flex 1.1, min 420px)            │ (flex 1.4, min 480px)         │
│                       │                                  │                               │
│ ┌───────────────────┐ │ Run r-8842 · Loan #LN-3391       │ ┌───────────────────────────┐ │
│ │ ⚑ Needs you    3  │ │ ● running · 00:47 · 12 steps     │ │ Credit Decision Memo      │ │
│ │ ◷ Waiting on co-  │ │                                  │ │ LN-3391 · Ortega, M.      │ │
│ │   signer       1  │ │ ✓ 1 Pull applicant profile  0.4s │ │───────────────────────────│ │
│ │ ▷ Running      2  │ │ ✓ 2 Retrieve credit bureau  1.2s │ │ Recommendation            │ │
│ │ ✓ Done today  14  │ │ ▼ 3 Underwrite  ⑂ 4 subagents    │ │  CONDITIONAL  conf 0.62   │ │
│ └───────────────────┘ │   ├ ✓ Income Verify     2.1s     │ │                           │ │
│                       │   ├ ✓ Collateral        1.7s     │ │ Requested   $450,000      │ │
│ ▸ ⚑ LN-3391  L2  4:12 │   ├ ● Debt Ratio     ▂▄▆ 3.9s    │ │ Term        30y fixed     │ │
│   Ortega — $450k loan │   └ ○ Fraud Screen   queued      │ │ DTI         44.1%  ⚠      │ │
│                       │ ○ 4 Compose memo                 │ │ LTV         91.2%  ⚠      │ │
│ ▸ ⚑ TX-77214 L1  9:58 │ ○ 5 Propose decision             │ │ Exceptions  POL-004       │ │
│   Velocity flag ×3    │                                  │ │                           │ │
│                       │ ─────────────────────────────    │ │ [Evidence ▾] [Sources ▾]  │ │
│ ▸ ⚑ AO-0912  L1 22:04 │ ⑂ SUPERVISOR AGENT (L2)          │ └───────────────────────────┘ │
│   KYC mismatch        │ ● forming independent opinion…   │                               │
│                       │                                  │ ╔═══════════════════════════╗ │
│ ▸ ▷ BATCH-31  running │                                  │ ║ ⚠ SIGNATURE REQUIRED  L2  ║ │
│   14 fee reversals    │                                  │ ║ expires in 04:12 → DENIED ║ │
│                       │                                  │ ║ [ Review payload ]        ║ │
│ ─────────────────────  │                                  │ ╚═══════════════════════════╝ │
│ Signed this session 6 │                                  │                               │
│ ████████░░ of 10      │                                  │                               │
├───────────────────────┴──────────────────────────────────┴───────────────────────────────┤
│ ⌘K  Ask or command…                             [live ●]  [⌥1 queue ⌥2 trace ⌥3 canvas]  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Note the command bar is a **thin strip at the bottom**, ~48px, spanning the full width. It is
not a pane. That single layout decision is what stops this reading as a chat app.

### 1.2 Pane responsibilities

**Task queue (left).** The banker's inbox. Grouped by *what it needs from you*, not by domain:

- `Needs you` — approval requests pending your signature. Sorted by TTL ascending (most urgent
  expiring first). This is the only default-expanded group.
- `Waiting on co-signer` — L2 items you initiated; you cannot self-co-sign (separation of
  duties), so these are read-only to you and show who they are waiting on.
- `Running` — runs in flight, no decision owed yet.
- `Done today` — collapsed, audit trail access.

Each row carries: domain badge (`LN` / `TX` / `AO` / `USR`), short title, **rung chip**, and
**TTL countdown**. Rung chip colours: L1 `info`, L2 `warning`, L3 `error` (L3 appears only as a
"blocked — outside harness" informational row, never as an actionable one).

**Plan / trace (centre).** §2. The centrepiece.

**Artifact canvas (right).** What the run *produced*. Tabbed when a run yields multiple
artifacts (`Memo` / `Comparison` / `Proposed payload` / `Raw evidence`). Approval cards dock at
the bottom of this pane, pinned, because the payload you are signing must be visually adjacent
to the evidence that justifies it. **Never put the approval in a modal** — a modal hides the
evidence behind the thing you are being asked to trust. That is precisely backwards.

### 1.3 What happens to the existing 7 admin tabs

Current `AdminPage.tsx` ships 8 tabs (the brief says 7; the code has 8 — Account Applications,
User Management, All Transactions, Flagged Transactions, Chatbot Prompt, AI Evaluation, Login
Audit, System Health).

**Recommendation, superseded by ruling — see below.** The original recommendation here was a
phased demotion ending in candidate removal. **Brian overruled that on 2026-09-04: Phase 5
changes from "admin tab retirement" to COEXISTENCE.** The tabs stay, behind a feature flag, so
the same banker task can be run on both surfaces and compared honestly. The buckets below are
still the right way to think about what each tab *is*; only the "fate" column changed.

| Bucket | Tabs | Fate |
|---|---|---|
| **Subsumed** — work the harness does better | Flagged Transactions, All Transactions, Account Applications | Become **task sources** feeding the queue and **tool surfaces** for the agent, *and* remain fully functional in `/admin`. These three are the comparison set: they are the only tabs where the same task genuinely exists on both surfaces, so they carry the entire measurement (§11). Retirement requires an explicit ruling backed by comparison data — it is no longer a scheduled phase. |
| **Retained, unchanged** — config/ops, not decision work | Chatbot Prompt, AI Evaluation, Login Audit, System Health | Stay in `/admin` permanently. These are operator/config surfaces with no per-item decision loop. Shoving them into an agent harness would be cargo-culting. |
| **Explicitly L3** | User Management (role promotion, deletes) | Stays in `/admin` **and** is on the harness's L3 deny-list. The agent may not even propose here. Worth a visible affordance in the harness: if a banker types "promote Ortega to admin", the harness responds with a **refusal card** naming L3 and linking to `/admin`. That refusal is a great demo beat — it proves the boundary is real. |

Rationale, which the ruling strengthens rather than changes: a "classic" surface de-risks the
rollout and — this matters — the harness's credibility depends on the banker being able to verify
what the agent claims. Ripping out the ground-truth tables makes the agent unfalsifiable. Keeping
both surfaces turns "the harness is a better experience" from a claim we assert into a hypothesis
we can lose. That is worth more than the claim was.

Nav: `AppShell` gets a second gated button. `Banker Copilot` (primary, `AutoAwesomeIcon`) and
`Admin`, relabelled **Classic Admin** whenever both surfaces are visible so the comparison is
legible in the chrome itself. Both remain `isAdmin`-gated with the existing pattern, and both are
additionally gated by a feature flag (§10).

### 1.4 Full-bleed without forking AppShell

`AppShell` currently hardwires `<Container maxWidth="lg" sx={{ py: 4 }}>`. Rather than
duplicate the shell, add an optional prop:

```ts
interface AppShellProps {
  children: React.ReactNode;
  /** Full-bleed layout: skips the maxWidth container and vertical padding.
   *  Used by dense multi-pane surfaces such as Banker Copilot. */
  disableContainer?: boolean;
}
```

`App.tsx` renders `/copilot` inside the shell with `disableContainer`. Small, surgical, no fork.
Danny should sign off on this since it touches shared chrome.

### 1.5 Responsive behaviour

Three panes below `lg` is a lie. Collapse strategy:

- `>= lg` (1200px): three panes as drawn.
- `md`–`lg`: queue collapses to a 56px icon rail with badge counts; trace + canvas split.
- `< md`: **single pane with a `Tabs` switcher** (`Queue | Trace | Artifact`), and any pending
  approval forces the tab to `Artifact` with the approval card in view. Mobile is a
  *triage-and-sign* surface, not an authoring one. We will not pretend a phone is a good place
  to underwrite a $450k loan; we will make it a good place to see that one is waiting.

---

## 2. The Live Trace Pane — the centrepiece

The thing people remember about GitHub Copilot's agent mode is **watching the plan change its
mind**. Most "AI assistant" panels render a spinner and then a wall of text. That throws away
the entire narrative. We render the narrative.

### 2.1 Structure

The trace is a **tree**, not a log. Root = the run. Children = plan steps. Plan step children =
tool calls and subagent runs. Subagent runs recurse.

```
Run r-8842 · Underwrite LN-3391                          ● RUNNING   00:47.3
│
├─ ✓  1  Pull applicant profile                                       0.42s
│      └─ 🔧 accounts.getCustomer(custId: "C-8891")            200 · 0.41s
│
├─ ✓  2  Retrieve credit bureau report                                1.21s
│      └─ 🔧 bureau.pull(ssnRef: "···4412", soft: true)        200 · 1.18s
│         ⚠ retried once (504 upstream)                        ↻ 1
│
├─ ▼  3  Underwrite                            ⑂ 4 subagents          3.9s…
│   │
│   ├─ ✓  Income Verification Agent                                   2.14s
│   │     conf 0.91  ·  3 tool calls  ·  "W-2 and 2y returns reconcile"
│   │
│   ├─ ✓  Collateral Agent                                            1.73s
│   │     conf 0.88  ·  2 tool calls  ·  "Appraisal $494k, LTV 91.2%"
│   │
│   ├─ ●  Debt Ratio Agent                        ▂▄▆▄▂                3.9s…
│   │     streaming · 2 tool calls so far
│   │
│   └─ ○  Fraud Screen Agent                      queued
│
├─ ○  4  Compose credit decision memo
├─ ○  5  Propose decision for signature
│
└─ ⑂  SUPERVISOR AGENT (independent, L2)          ●  forming opinion…
      ▸ does NOT see the primary agent's recommendation
```

### 2.2 State vocabulary and how each renders

| State | Glyph | Render |
|---|---|---|
| `pending` | `○` | 40% opacity, no timer. Future steps are visible but ghosted — **this is what makes re-planning legible.** You can see the shape of the plan before it happens, so when it changes you *notice*. |
| `running` | `●` | Accent ring + a live elapsed timer + a 5-bar activity sparkline that pulses on each token/tool event. |
| `complete` | `✓` | Settles to a fixed duration chip. Subtle green left border. |
| `failed` | `✗` | `error` colour, error text inline, retry affordance if the agent retried. |
| `retrying` | `↻ n` | Amber, retry counter, previous attempt collapsible. |
| `skipped` | `⊘` | Struck through, with the reason ("superseded by re-plan"). |

### 2.3 Re-planning — the money moment

When the agent re-plans, do **not** silently swap the list. Animate it:

1. Removed/superseded steps **collapse with a strikethrough** and drop to a `Superseded (2)`
   collapsible group. They do not vanish. Vanishing destroys trust.
2. Inserted steps **slide in** with a one-shot highlight flash (MUI `Fade` + a 600ms background
   transition on `warning.light` → transparent).
3. A `PlanRevisionMarker` divider is stamped inline: `── plan revised · v2 · "DTI exceeded
   threshold, adding exception analysis" ──`.
4. **If a signature was already outstanding, this is the moment it goes void.** See §5.4.

In a live demo, the audience literally watches the agent reconsider. That is the shot.

### 2.4 Subagent fan-out

Subagents render as **nested, independently-collapsible sub-trees** with their own timers and
confidence chips. Rules:

- Fan-out is animated: the four children stagger in ~80ms apart. It reads as a fan, not a dump.
- Each subagent shows a **one-line verdict** when it completes (`conf 0.91 · "W-2 and 2y returns
  reconcile"`). This is the unit of skimmability — the banker should be able to read four
  one-liners and know where the risk is.
- Depth is capped at **3** in the visual tree. Deeper nesting renders as a flattened
  `↳ depth 4+` group behind a disclosure. Nobody can parse a 6-deep tree live.
- The **supervisor agent renders as a sibling of the root plan, not a child**, with a distinct
  left border colour and an explicit `does NOT see the primary agent's recommendation` caption.
  Its visual separation is the UI's assertion of independence, and it sets up §5.3.

### 2.5 Density controls

Three-position density toggle in the trace header — this matters because the same pane serves
two audiences (banker skimming, engineer debugging):

- **Summary** — plan steps only, tool calls collapsed to a count chip. Default.
- **Detailed** — plan steps + tool call names + durations. Demo default.
- **Raw** — full tool arguments and responses, JSON-rendered, virtualised. Redaction still
  applies (see §7.5).

Plus a `Timings` toggle that swaps duration chips for a **mini Gantt** — proportional-width bars
on a shared timeline, so parallel subagent execution is *visibly* parallel. Cheap to build
(flexbox + percentage widths), disproportionately impressive.

### 2.6 Autoscroll

Follow-the-tail by default, but **release on any user scroll-up** and show a
`↓ 4 new steps` pill to jump back. Non-negotiable: a banker reading step 2 while the agent
writes step 9 must not be yanked away. (Same bug class as `Chat.tsx`'s unconditional
`scrollIntoView` — deliberately not repeating it.)

### 2.7 What makes it demo-compelling — explicitly

1. **Ghosted future steps.** The plan's shape is visible before execution, so mutation is
   obvious.
2. **Staggered subagent fan-out.** Four agents blooming under one step.
3. **The Gantt toggle.** Parallelism you can see.
4. **The plan revision marker.** The agent visibly changing its mind, with a reason.
5. **The supervisor agent's separate rail** turning from `forming opinion…` to a verdict that
   **disagrees**. That's the peak (§8).

---

## 3. Component Inventory

New folder: `src/ui-app/src/components/copilot/`, mirroring the existing
`components/eval/` and `components/account-opening/` convention. Shared types in
`components/copilot/types.ts` (matching `components/eval/types.ts` precedent).

### 3.1 Hierarchy

```
pages/BankerCopilotPage.tsx
└── CopilotHarness                        (layout + context provider)
    ├── TaskQueuePane
    │   ├── TaskQueueGroup                (Needs you / Waiting / Running / Done)
    │   │   └── TaskQueueItem
    │   │       ├── AuthorityRungChip
    │   │       └── ApprovalCountdown
    │   └── SessionApprovalMeter          (anti-fatigue, §6)
    ├── TracePane
    │   ├── TraceHeader                   (run title, status, density, timings toggle)
    │   ├── TraceTree
    │   │   ├── PlanStepNode
    │   │   │   ├── ToolCallNode
    │   │   │   └── SubagentNode          (recursive → TraceTree)
    │   │   ├── PlanRevisionMarker
    │   │   └── SupervisorAgentRail
    │   ├── TraceGanttStrip               (optional overlay)
    │   └── TraceLiveRegion               (visually hidden, aria-live — §7.2)
    ├── ArtifactCanvas
    │   ├── ArtifactTabs
    │   ├── DecisionMemoArtifact
    │   ├── PayloadArtifact               (structured payload renderer)
    │   ├── EvidenceList
    │   └── ApprovalDock                  (pinned bottom)
    │       ├── ApprovalCard              (L1)
    │       ├── DualControlApprovalCard   (L2 — side-by-side opinions)
    │       ├── EscalatorExplainer
    │       ├── PayloadDiffView           (signature-void state)
    │       ├── BatchApprovalCard         (single action type, sub-threshold)
    │       └── SignatureConfirm          (typed confirmation / forced dwell)
    ├── L3RefusalCard
    ├── CommandBar                        (⌘K, bottom strip)
    └── StreamStatusIndicator             (live / reconnecting / dropped)
```

### 3.2 Core domain types (`components/copilot/types.ts`)

```ts
export type RunStatus =
  | 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled';

export type NodeStatus =
  | 'pending' | 'running' | 'complete' | 'failed' | 'retrying' | 'skipped';

export type AuthorityRung = 'L1' | 'L2' | 'L3';

export type EscalatorCode =
  | 'SELF_DEALING'
  | 'BULK_FANOUT'
  | 'VELOCITY'
  | 'LOW_CONFIDENCE'
  | 'POLICY_EXCEPTION'
  | 'HIGH_RISK_CUSTOMER'
  | 'ANOMALOUS_SESSION';

export interface Escalator {
  code: EscalatorCode;
  /** Plain-language sentence rendered verbatim to the banker. Server-supplied,
   *  never assembled client-side — the explanation is part of the audit record. */
  explanation: string;
  /** Rung before and after this escalator fired. Escalators only ever raise. */
  fromRung: AuthorityRung;
  toRung: AuthorityRung;
  /** Optional policy reference, e.g. 'POL-004'. */
  policyRef?: string;
}

export interface ToolCall {
  id: string;
  name: string;                       // e.g. 'bureau.pull'
  args?: Record<string, unknown>;     // redacted server-side
  status: NodeStatus;
  startedAt: string;
  durationMs?: number;
  resultSummary?: string;
  error?: string;
  attempt: number;                    // 1-based; >1 renders the retry chip
}

export interface SubagentRun {
  id: string;
  parentStepId: string;
  name: string;                       // 'Income Verification Agent'
  role: 'specialist' | 'supervisor';
  status: NodeStatus;
  confidence?: number;                // 0..1
  verdictSummary?: string;
  startedAt: string;
  durationMs?: number;
  toolCalls: ToolCall[];
  children: SubagentRun[];            // recursive fan-out
  depth: number;
}

export interface PlanStep {
  id: string;
  index: number;
  title: string;
  status: NodeStatus;
  startedAt?: string;
  durationMs?: number;
  toolCalls: ToolCall[];
  subagents: SubagentRun[];
  /** Set when a re-plan superseded this step. */
  supersededByApprovalId?: string;
  supersededReason?: string;
}

export interface PlanRevision {
  version: number;
  at: string;
  reason: string;
  addedStepIds: string[];
  removedStepIds: string[];
  /** Set when this revision superseded an outstanding approval, stopping its signature counting. */
  supersededApprovalId?: string;
}
```

### 3.3 Approval types

```ts
// Canonical lifecycle — epic §5.1. There is no 'expired' and no 'void' state:
// both are 'denied' differentiated by terminalReason (epic §5.1.1).
export type ApprovalState =
  | 'proposed' | 'pending' | 'signed' | 'executed' | 'denied';

// Closed set — epic §5.1.1. Mandatory whenever state === 'denied'.
// Never aggregate a denial count across these; see §5.1.1(c).
export type TerminalReason =
  | 'HUMAN_DENIED' | 'POLICY_RUNG_ESCALATED' | 'TTL_EXPIRED' | 'PAYLOAD_SUPERSEDED';

export interface PayloadField {
  path: string;                       // 'amount' | 'terms.rate'
  label: string;
  value: unknown;
  /** Rendering hint so money never renders as a bare number. */
  format?: 'currency' | 'percent' | 'date' | 'text' | 'accountRef' | 'json';
  /** Marks the fields a human MUST read. Drives progressive disclosure (§6). */
  material?: boolean;
}

export interface AgentOpinion {
  agentId: string;
  agentName: string;
  role: 'primary' | 'supervisor';
  verdict: 'APPROVE' | 'CONDITIONAL' | 'DECLINE';
  confidence: number;                 // 0..1
  rationale: string;
  keyFactors: { label: string; value: string; concern?: boolean }[];
  citedEvidenceIds: string[];
}

export interface ApprovalRequest {
  id: string;
  runId: string;
  taskId: string;
  actionType: string;                 // 'loan.decision' | 'transaction.clear' | ...
  title: string;
  state: ApprovalState;
  /** Rung the signature must satisfy, and the rung before escalators fired. */
  requiredRung: AuthorityRung;
  baseRung: AuthorityRung;
  firedEscalators: Escalator[];
  /** The signature binds to THIS hash. Server-computed. */
  payloadHash: string;
  payload: PayloadField[];
  evidence: EvidenceRef[];
  /** Primary agent opinion always present; supervisor present iff requiredRung === 'L2'. */
  opinions: AgentOpinion[];
  /** Identity the agent acted under. Also the Cosmos partition key. */
  requesterId: string;
  /**
   * Populated as signatures land. L2 requires two, from DIFFERENT identities.
   *
   * There is deliberately NO `cosignerId` field. Naming a prospective co-signer
   * at proposal time would let a banker choose their own reviewer, which is the
   * exact self-dealing pattern L2 exists to prevent. The UI therefore renders
   * "awaiting a supervisor" and NEVER a named prospective co-signer. See §5.3.
   */
  signatures: Signature[];
  requiredSigners: 1 | 2;
  expiresAt: string;                  // ISO. Expiry === denied/TTL_EXPIRED.
  createdAt: string;
  /** MANDATORY when state === 'denied'. Never render a bare "Denied". */
  terminalReason?: TerminalReason;
  /** Set together with terminalReason. */
  terminalAt?: string;
  /** Free-text detail. For HUMAN_DENIED this is the banker's reason (min 20 chars). */
  terminalDetail?: string;
  supersededByApprovalId?: string;
  previousPayload?: PayloadField[];   // drives PayloadDiffView
}

export interface Signature {
  actor: ActorRef;
  signedAt: string;
  decision: 'signed' | 'denied';
  payloadHash: string;                // must match — client asserts and warns if not
  note?: string;
  /** ms the signer had the material fields visible. Anti-fatigue telemetry. */
  dwellMs?: number;
}

export interface ActorRef {
  id: string;
  displayName: string;
  role: 'banker' | 'supervisor' | 'agent';
}

export interface EvidenceRef {
  id: string;
  kind: 'document' | 'tool_result' | 'record' | 'policy';
  label: string;
  sourceToolCallId?: string;
  excerpt?: string;
  href?: string;
}
```

### 3.4 Selected component props

```ts
interface TraceTreeProps {
  steps: PlanStep[];
  revisions: PlanRevision[];
  supervisor?: SubagentRun;
  density: 'summary' | 'detailed' | 'raw';
  showTimings: boolean;
  runStartedAt: string;
  onSelectNode?: (nodeId: string) => void;
}

interface ApprovalCardProps {
  request: ApprovalRequest;
  currentActor: ActorRef;
  /** False when currentActor already signed (separation of duties) or lacks the rung. */
  canSign: boolean;
  blockedReason?: 'separation_of_duties' | 'insufficient_authority' | 'terminal';
  onSign: (note?: string, dwellMs?: number) => Promise<void>;
  onDeny: (reason: string) => Promise<void>;
}

interface DualControlApprovalCardProps extends ApprovalCardProps {
  primary: AgentOpinion;
  supervisor: AgentOpinion;
  /** Server-computed. Drives the prominent disagreement treatment. */
  disagreement: {
    kind: 'none' | 'verdict' | 'confidence' | 'both';
    summary: string;
    divergentFactors: string[];
  };
}

interface EscalatorExplainerProps {
  firedEscalators: Escalator[];
  baseRung: AuthorityRung;
  requiredRung: AuthorityRung;
  variant?: 'inline' | 'expanded';
}

interface ApprovalCountdownProps {
  expiresAt: string;
  /** Copy is unambiguous: "expires in 04:12 → DENIED". Never "auto-approves". */
  onExpire?: () => void;
  size?: 'small' | 'medium';
}

interface PayloadDiffViewProps {
  previous: PayloadField[];
  next: PayloadField[];
  /** Highlights material-field changes distinctly from cosmetic ones. */
  emphasizeMaterial?: boolean;
}
```

### 3.5 Reuse vs. new

**Reuse / adapt:**

| Existing | How it's used |
|---|---|
| `components/account-opening/ApplicationStages.tsx` + `AgentPipeline.tsx` | Its `StageStatus` union (`pending / in_progress / completed / failed`) and the confidence + reasoning + timestamp card shape are exactly the trace node's ancestor. `PlanStepNode` is a denser, streaming-aware evolution of `ApplicationStages`. **Do not extend `ApplicationStages` in place** — it's a horizontal `Stepper` and the trace is a vertical tree. Copy the vocabulary, not the layout. Align `NodeStatus` naming with a small mapping helper so the two don't drift. |
| `components/eval/EvaluationResults.tsx` | Score/verdict rendering patterns and the pass/fail chip idiom carry straight into `AgentOpinion` rendering. |
| `components/eval/types.ts` | Type-file convention (flat interfaces, no enums, string unions) — followed exactly. |
| `FlaggedTransactionsTab.tsx` / `AllTransactionsTab.tsx` | Row shape, risk-score chips, and the `formatRiskScore` guard from `AdminPage.tsx` (the 0–1 sanity clamp from #119). **Reuse `formatRiskScore` — promote it to `utils/format.ts`** rather than copy-pasting a third instance. |
| `components/account-opening/AdminApplicationsTab.tsx` | Existing admin decision flow; its approve/reject affordances show what *not* to do (single-click, no dwell, no evidence adjacency). |
| `api/errors.ts`, `utils/logger.ts`, `ErrorBoundary.tsx` | Error normalisation, logging, and pane-level error isolation. Each pane gets its own `ErrorBoundary section="..."` so a trace render bug cannot take down the approval dock. |
| `api/client.ts` | All non-streaming calls (submit intent, sign, deny). Streaming needs its own transport (§4). |

**Must be new:** everything under `components/copilot/`, plus the stream client
(`api/copilotStream.ts`), the store (`state/copilotStore.ts`), and the `useCopilotRun` /
`useApprovalQueue` hooks.

---

## 4. Streaming Client Design

### 4.1 SSE vs WebSocket — recommendation: **SSE over `fetch`** (not native `EventSource`)

The traffic is overwhelmingly **server → client**. Client → server events are rare, discrete,
and high-stakes: submit intent, sign, deny, cancel. Those want request/response semantics with
real HTTP status codes, idempotency keys, and retry — *not* a fire-and-forget socket frame.
**Signing a $450k loan over a WebSocket message with no HTTP status is a bad idea**, and if we
built the socket we would be tempted to do exactly that.

| Criterion | SSE (fetch) | WebSocket |
|---|---|---|
| Direction fit | Ideal — unidirectional | Overkill |
| Auth (bearer in `localStorage`) | `Authorization` header works with `fetch` | Requires subprotocol/query-param hacks; query-param tokens leak into logs |
| Resume | `Last-Event-ID` semantics, ours to implement over the same header | Hand-rolled |
| Proxy/infra | Plain HTTP through the existing nginx gateway; **needs `proxy_buffering off`** | Needs `Upgrade`/`Connection` headers configured per-route |
| Signing path | Ordinary `POST` via `apiClient` — interceptors, 401 redirect, error normalisation all reused | Reinvented |
| Foundry Agent Service | Emits token/step streams that map cleanly to SSE frames | Extra bridging |
| Debuggability | Readable in devtools Network tab; `curl`-able | Binary-ish frame inspector |

**Why not native `EventSource`:** it cannot set an `Authorization` header. Our token lives in
`localStorage` and is attached by an axios interceptor (`api/client.ts`). Native `EventSource`
would force the token into the query string — which lands in nginx access logs, browser
history, and any APM span. Unacceptable for a banking demo that we hold up as a security
exemplar. `fetch` + `ReadableStream` + a small SSE frame parser gives us headers, `AbortSignal`
cancellation, and POST-to-open (so the intent payload rides the opening request rather than a
URL).

**Infra dependency to flag to Danny/Turk:** `infra/local/gateway.nginx.conf` has no
`proxy_buffering off` on any `/api/` location. Without it nginx buffers the whole response and
the "live" trace arrives as one lump at the end — the demo dies. The copilot stream route needs
`proxy_buffering off; proxy_cache off; proxy_read_timeout 300s; chunked_transfer_encoding on;`
and the same treatment on the cloud ingress. **This is the single highest-risk non-frontend
dependency for this epic.** Flagging early, deliberately.

### 4.2 Event envelope

```ts
/** Every frame shares this envelope. `seq` is monotonic per run and is the
 *  basis for dedupe, ordering, and resume. */
export interface CopilotEventEnvelope<K extends CopilotEventKind, P> {
  /** Globally unique event id; also emitted as the SSE `id:` field. */
  id: string;
  /** Monotonic, gapless per run. Gaps mean we missed frames → resync. */
  seq: number;
  runId: string;
  kind: K;
  /** Server clock, ISO 8601. Never trust the client clock for TTLs. */
  ts: string;
  payload: P;
}

export type CopilotEventKind =
  | 'run.started'
  | 'plan.proposed'
  | 'plan.revised'
  | 'step.started'
  | 'step.completed'
  | 'step.failed'
  | 'tool.started'
  | 'tool.completed'
  | 'tool.failed'
  | 'subagent.spawned'
  | 'subagent.progress'
  | 'subagent.completed'
  | 'approval.required'
  | 'approval.updated'
  | 'approval.terminal'
  | 'artifact.created'
  | 'artifact.updated'
  | 'run.error'
  | 'run.done'
  | 'heartbeat';
```

Per-kind payloads:

```ts
export interface RunStartedPayload {
  taskId: string;
  title: string;
  intent: string;
  actor: ActorRef;
  startedAt: string;
}

export interface PlanProposedPayload {
  version: number;
  steps: Pick<PlanStep, 'id' | 'index' | 'title' | 'status'>[];
}

export interface PlanRevisedPayload extends PlanRevision {
  steps: Pick<PlanStep, 'id' | 'index' | 'title' | 'status'>[];
}

export interface StepStartedPayload  { stepId: string; index: number; title: string; }
export interface StepCompletedPayload{ stepId: string; durationMs: number; summary?: string; }
export interface StepFailedPayload   { stepId: string; error: string; willRetry: boolean; }

export interface ToolStartedPayload {
  toolCallId: string; stepId: string; subagentId?: string;
  name: string; args?: Record<string, unknown>; attempt: number;
}
export interface ToolCompletedPayload {
  toolCallId: string; durationMs: number; resultSummary?: string;
  result?: unknown;                 // present only at 'raw' density subscription
}
export interface ToolFailedPayload {
  toolCallId: string; error: string; attempt: number; willRetry: boolean;
}

export interface SubagentSpawnedPayload {
  subagentId: string; parentStepId: string; parentSubagentId?: string;
  name: string; role: 'specialist' | 'supervisor'; depth: number;
}
export interface SubagentProgressPayload {
  subagentId: string; note?: string; toolCallCount: number;
}
export interface SubagentCompletedPayload {
  subagentId: string; status: 'complete' | 'failed';
  confidence?: number; verdictSummary?: string; durationMs: number;
}

export interface ApprovalRequiredPayload  { request: ApprovalRequest; }
export interface ApprovalUpdatedPayload   { request: ApprovalRequest; }

/**
 * Fired when an approval reaches ANY terminal state — the four denial reasons
 * and `executed` alike.
 *
 * Renamed from the earlier `approval.voided`: there is no `void` lifecycle
 * state, so an event named for one would reintroduce in the client exactly the
 * distinction epic §5.1.1 collapsed into `terminalReason`. The UI's dramatic
 * "signature void" treatment (§5.4) is a RENDERING of
 * `terminalReason === 'PAYLOAD_SUPERSEDED'`, not a separate state.
 */
export interface ApprovalTerminalPayload {
  approvalId: string;
  state: 'denied' | 'executed';
  terminalReason?: TerminalReason;    // mandatory when state === 'denied'
  terminalDetail?: string;
  terminalAt: string;
  previousPayloadHash: string;
  supersededByApprovalId?: string;
}

export interface ArtifactPayload {
  artifactId: string;
  kind: 'decision_memo' | 'payload' | 'comparison' | 'evidence_bundle';
  title: string;
  /** Artifacts may stream in fragments; `revision` increments per update. */
  revision: number;
  content: unknown;
}

export interface RunErrorPayload {
  code: string; message: string; recoverable: boolean; stepId?: string;
}
export interface RunDonePayload {
  status: 'completed' | 'failed' | 'cancelled';
  durationMs: number;
  finalArtifactIds: string[];
  /** Terminal seq — client asserts it saw every seq up to this. */
  finalSeq: number;
}
export interface HeartbeatPayload { serverTs: string; }

export type CopilotEvent =
  | CopilotEventEnvelope<'run.started', RunStartedPayload>
  | CopilotEventEnvelope<'plan.proposed', PlanProposedPayload>
  | CopilotEventEnvelope<'plan.revised', PlanRevisedPayload>
  | CopilotEventEnvelope<'step.started', StepStartedPayload>
  | CopilotEventEnvelope<'step.completed', StepCompletedPayload>
  | CopilotEventEnvelope<'step.failed', StepFailedPayload>
  | CopilotEventEnvelope<'tool.started', ToolStartedPayload>
  | CopilotEventEnvelope<'tool.completed', ToolCompletedPayload>
  | CopilotEventEnvelope<'tool.failed', ToolFailedPayload>
  | CopilotEventEnvelope<'subagent.spawned', SubagentSpawnedPayload>
  | CopilotEventEnvelope<'subagent.progress', SubagentProgressPayload>
  | CopilotEventEnvelope<'subagent.completed', SubagentCompletedPayload>
  | CopilotEventEnvelope<'approval.required', ApprovalRequiredPayload>
  | CopilotEventEnvelope<'approval.updated', ApprovalUpdatedPayload>
  | CopilotEventEnvelope<'approval.terminal', ApprovalTerminalPayload>
  | CopilotEventEnvelope<'artifact.created', ArtifactPayload>
  | CopilotEventEnvelope<'artifact.updated', ArtifactPayload>
  | CopilotEventEnvelope<'run.error', RunErrorPayload>
  | CopilotEventEnvelope<'run.done', RunDonePayload>
  | CopilotEventEnvelope<'heartbeat', HeartbeatPayload>;
```

The discriminated union on `kind` means the reducer is exhaustively type-checked. A new event
kind added server-side without a client handler becomes a **compile error**, not a silent
no-op. That is the point of doing it this way.

### 4.3 Client shape

```ts
export interface CopilotStreamOptions {
  runId?: string;                 // omit to open a new run
  intent?: string;                // rides the opening POST body
  lastSeq?: number;               // resume cursor
  onEvent: (event: CopilotEvent) => void;
  onStatusChange: (status: StreamStatus) => void;
  signal?: AbortSignal;
}

export type StreamStatus =
  | 'connecting' | 'live' | 'reconnecting' | 'resumed' | 'degraded' | 'closed' | 'failed';

export function openCopilotStream(opts: CopilotStreamOptions): CopilotStreamHandle;

export interface CopilotStreamHandle {
  close(): void;
  status(): StreamStatus;
  lastSeq(): number;
}
```

`useCopilotStream(runId)` wraps this and feeds the store. Transport lives in
`src/ui-app/src/api/copilotStream.ts`, next to `client.ts`.

### 4.4 Ordering, duplicates, gaps

- **Duplicates:** the reducer keeps `lastSeq`. Any event with `seq <= lastSeq` is **dropped**.
  All reducer operations are additionally written to be **idempotent** (upsert by node id, never
  push-append), so a duplicate that slips through is harmless. Belt and braces, because on a
  reconnect the server will legitimately replay.
- **Out-of-order:** SSE over one TCP connection is ordered, so out-of-order only occurs *across*
  a reconnect. Events arriving with `seq > lastSeq + 1` indicate a **gap**: buffer them in a
  small pending map (cap 200), request replay from `lastSeq`, and drain the buffer once
  contiguous. If the gap can't be closed in 5s, escalate to a full `GET /copilot/runs/:id`
  snapshot refetch and hard-reset the run state. **Never render a known-incomplete trace as if
  it were complete** — a trace with silently missing steps is worse than no trace.
- **Late events after `run.done`:** dropped, logged via `utils/logger.ts`.

### 4.5 Reconnection and resume

Exponential backoff with jitter: 500ms → 1s → 2s → 4s → 8s, cap 15s, unlimited attempts while
the tab is visible. On reconnect, `POST /api/copilot/runs/:id/stream` with `lastSeq`; server
replays from `lastSeq + 1`. Server retains a bounded replay window; if the cursor has fallen out
of it, the server responds `409` with a `resync_required` code and the client does a snapshot
refetch.

- **Heartbeat:** every 15s. Missing two consecutive → `degraded`, force reconnect. Without this
  a half-open TCP connection looks identical to "the agent is thinking", which is the worst
  possible ambiguity on this surface.
- **Tab hidden:** keep the stream open (runs are short); on `visibilitychange` back to visible,
  if `> 60s` elapsed, force a snapshot refetch to be safe.
- **Never resume by replaying UI animations.** Resumed events set state directly; the
  highlight-flash animations are suppressed during drain (a `isDraining` flag in the store),
  otherwise a resume produces a seizure-inducing 200-step flash cascade.

### 4.6 What the user sees when the stream drops

Graduated, and honest. The rule: **never let a dead stream look like a working one.**

| Status | Treatment |
|---|---|
| `live` | Small green dot + `live` in the command bar. Nothing else. |
| `reconnecting` | Amber dot, inline banner above the trace: `Reconnected in… the agent is still running on the server.` Trace freezes at last-known state and **running nodes dim from pulsing to static** — the pulse is a promise of liveness and must not lie. |
| `resumed` | Green flash + `Caught up — 12 steps recovered` toast, auto-dismiss 4s. |
| `degraded` | Same as reconnecting plus `Retrying (4)…` and a manual `Retry now` button. |
| `failed` (backoff exhausted / auth failure) | Red banner: `Live updates unavailable. The run continues on the server.` Trace becomes read-only-with-refresh, with a prominent `Refresh` that snapshot-refetches. |

**Critical:** on any non-`live` status, **all approval sign/deny buttons disable** with the
tooltip `Reconnecting — cannot verify this is still the current payload.` We must not let a
banker sign against a stale payload during a network partition. That is the entire TOCTOU threat
the payload-hash design exists to prevent, and the UI must not undo it. The TTL countdown keeps
running (it's server-clock-anchored) and, if it lapses while disconnected, renders `DENIED —
SIGNATURE WINDOW CLOSED` (`terminalReason = TTL_EXPIRED`) on reconnect like any other lapse.

---

## 5. Approval UX — the highest-stakes screens

These screens are the product's integrity. Everything else is a nice demo; this is the part that
decides whether "agents never approve" is true or decorative.

Three principles:

1. **Evidence adjacency.** The payload and the evidence justifying it must be on screen
   simultaneously. No modals, no "view details" round trips for material facts.
2. **Verifiability, not summarisation.** The banker must be able to check the agent's claim, not
   just read the agent's confidence. Every material number links to the tool call that produced
   it.
3. **Friction proportional to stakes.** A $200 fee reversal and a $450k loan must not cost the
   same number of clicks. Uniform friction is how you get rubber-stamping.

### 5.1 The L1 approval card

```
╔══════════════════════════════════════════════════════════════════════════╗
║  SIGNATURE REQUIRED                                    ⬤ L1  ONE SIGNER  ║
║  Clear flagged transaction TX-77214                                      ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  ◷ Expires in 09:58   →  on expiry this is DENIED, not approved          ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  WHY L1                                                                  ║
║   Base rung for "clear flagged transaction" under $10,000.               ║
║   No escalators fired.                                       [details ▾] ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  YOU ARE SIGNING                                                         ║
║   Action        transaction.clear                                        ║
║   Transaction   TX-77214                                                 ║
║   Amount        $4,120.00              ← material                        ║
║   Account       ····8891  (M. Ortega)  ← material                        ║
║   Effect        Removes fraud hold; funds settle same day.  ← material   ║
║   Reversible    Yes — re-flag within 24h                                 ║
║                                                     payload ····a4f9e2c1 ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  AGENT RECOMMENDATION            APPROVE · confidence 0.89               ║
║   "Merchant and geo match 14 months of history; the velocity spike is    ║
║    a known payroll-cycle pattern for this customer."                     ║
║   Evidence  ▸ Txn history 14mo (tool: transactions.query)      [open]    ║
║             ▸ Device fingerprint match (tool: risk.deviceCheck)[open]    ║
║             ▸ Prior 3 cleared velocity flags                   [open]    ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  ☐ I reviewed the amount, account, and effect above                      ║
║                                                                          ║
║   [ Deny ]              [ Sign — clear TX-77214 ]   (enabled in 0:03)    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

Details that are load-bearing, not decoration:

- **Button label states the action.** `Sign — clear TX-77214`, never `Approve`. `Approve` is the
  word we are reserving for a thing agents may never do; using it as a generic button label
  cheapens the distinction we are trying to teach.
- **`Effect` is a plain-language, server-supplied sentence** describing what changes in the
  world. Bankers verify effects, not JSON. `PayloadArtifact` renders `format: 'currency'` as
  `$4,120.00` — a mis-rendered magnitude here is a real-world loss event.
- **`Reversible`** is shown because it legitimately changes how careful you should be, and
  hiding it produces uniform paranoia, which decays into uniform inattention.
- **Payload hash** rendered short (`····a4f9e2c1`) with the full value on hover. It is the anchor
  for §5.4 and it should be visible so that "the payload changed" is a *checkable* claim.
- **Evidence rows link back to the originating tool call in the trace pane.** Clicking scrolls
  and highlights the node. This is the loop that makes the trace pane useful rather than
  ornamental: the trace is the citation index for the recommendation.
- **Dwell gate:** the sign button is disabled for a minimum dwell period scaled to stakes (§6.2)
  with a visible countdown so it reads as deliberate design, not lag.

### 5.2 Denial is a first-class path

`Deny` is not a secondary "cancel". It requires a **reason** (select + free text) because the
denial reason is training signal and audit record. Same visual weight as `Sign`, `error`-toned
outline. A UI where denial is harder than approval has its thumb on the scale.

### 5.3 The L2 dual-control card — and the disagreement moment

L2 shows **two independent opinions side by side.** The supervisor agent forms its opinion
without visibility into the primary's recommendation, and the UI states that explicitly — the
claim of independence is worthless if invisible.

**Agreement state** (calm, still requires two human signatures):

```
╔══════════════════════════════════════════════════════════════════════════╗
║  SIGNATURE REQUIRED           ⬤ L2  TWO SIGNERS · SEPARATION OF DUTIES   ║
║  ┌─── PRIMARY AGENT ──────────────┐ ┌─── SUPERVISOR AGENT ─────────────┐ ║
║  │ CONDITIONAL      conf 0.71     │ │ CONDITIONAL      conf 0.68       │ ║
║  │ …                              │ │ …                                │ ║
║  └────────────────────────────────┘ └──────────────────────────────────┘ ║
║  ✓ Independent review reached the same verdict.                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**Disagreement state** — the most important screen in the entire epic:

```
╔══════════════════════════════════════════════════════════════════════════╗
║  SIGNATURE REQUIRED           ⬤ L2  TWO SIGNERS · SEPARATION OF DUTIES   ║
║  Loan decision — LN-3391 · Ortega, M. · $450,000                         ║
║  ◷ Expires in 04:12  →  on expiry this is DENIED                         ║
╠══════════════════════════════════════════════════════════════════════════╣
║  ⚠⚠  THE TWO AGENTS DISAGREE.  A HUMAN MUST DECIDE.               ⚠⚠     ║
║      Primary recommends CONDITIONAL. Supervisor recommends DECLINE.      ║
║      They diverge on: debt-to-income treatment, POL-004 exception.       ║
╠═══════════════════════════════════╦══════════════════════════════════════╣
║ PRIMARY AGENT                     ║ SUPERVISOR AGENT      (independent)  ║
║ ┌───────────────────────────────┐ ║ ┌──────────────────────────────────┐ ║
║ │  CONDITIONAL                  │ ║ │  DECLINE                         │ ║
║ │  confidence 0.62  ▓▓▓▓▓▓░░░░  │ ║ │  confidence 0.81  ▓▓▓▓▓▓▓▓░░     │ ║
║ └───────────────────────────────┘ ║ └──────────────────────────────────┘ ║
║                                   ║                                      ║
║ "Approve with 25% down and a      ║ "Decline. DTI of 44.1% exceeds the   ║
║  6-month reserve requirement.     ║  38% ceiling and the compensating    ║
║  Compensating factors: 9 years    ║  factors cited are not durable —     ║
║  at employer, 780 FICO, and       ║  bonus income accounts for 31% of    ║
║  $180k in liquid reserves."       ║  qualifying income and has fallen    ║
║                                   ║  two years running. POL-004 is not   ║
║                                   ║  intended for variable-comp cases."  ║
║                                   ║                                      ║
║ KEY FACTORS                       ║ KEY FACTORS                          ║
║  DTI          44.1%   ⚠           ║  DTI          44.1%   ✗ over ceiling ║
║  FICO         780     ✓           ║  FICO         780     ✓              ║
║  LTV          91.2%   ⚠           ║  LTV          91.2%   ✗ w/o 25% down ║
║  Reserves     $180k   ✓           ║  Bonus income 31%     ✗ ← DIVERGENT  ║
║  Tenure       9y      ✓           ║  POL-004 fit  poor    ✗ ← DIVERGENT  ║
║                                   ║                                      ║
║  cites 6 evidence items  [view]   ║  cites 9 evidence items  [view]      ║
╠═══════════════════════════════════╩══════════════════════════════════════╣
║  WHY THIS IS L2                                                          ║
║   ▲ Amount $450,000 exceeds the $250,000 single-signature ceiling.       ║
║   ▲ Policy exception POL-004 was invoked (DTI above standard limit).     ║
║   ▲ Agent confidence 0.62 is below the 0.75 single-signature floor.      ║
║   Base rung L1 → raised to L2. Escalators never lower a rung.            ║
╠══════════════════════════════════════════════════════════════════════════╣
║  YOU ARE SIGNING     [ Primary's CONDITIONAL ▾ ]   payload ····7b21ffd0  ║
║   Principal   $450,000    Rate   6.875%   Term  30y fixed                ║
║   Conditions  25% down ($112,500) · 6-month reserve · re-verify bonus    ║
║   Effect      Issues a conditional commitment letter to the applicant.   ║
║   Reversible  No — commitment letters are binding once issued.  ⚠        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  SIGNATURES                                                              ║
║   1. B. Denicola (acting banker)              ✓ signed  09:14:22         ║
║   2. Supervisor — required, must be a different person       ◷ awaiting  ║
║      You cannot sign twice. Separation of duties.                        ║
║                                                                          ║
║  ⚠ You are overriding the supervisor agent's DECLINE. State why:         ║
║  ┌──────────────────────────────────────────────────────────────────┐    ║
║  │                                                                  │    ║
║  └──────────────────────────────────────────────────────────────────┘    ║
║   [ Deny ]   [ Request more analysis ]   [ Co-sign — issue commitment ]  ║
║                                              (enabled in 0:14)           ║
╚══════════════════════════════════════════════════════════════════════════╝
```

Design decisions worth defending:

- **Disagreement is a full-width banner above both columns**, not a chip. It is the single most
  decision-relevant fact on the screen. `error.light` background, doubled warning glyphs,
  `role="alert"`. When it appears mid-stream it gets a one-shot attention animation.
- **Divergent factors are marked on both sides** (`← DIVERGENT`). The banker's job collapses
  from "read two essays" to "adjudicate two specific disputes". That's the whole value.
- **Confidence bars are visually comparable.** The supervisor being *more* confident in the
  opposite direction is the uncomfortable, interesting fact. Do not bury it in a decimal.
- **You must pick which recommendation you are signing.** The `[ Primary's CONDITIONAL ▾ ]`
  selector re-renders the payload block. There is no neutral "approve" that papers over the
  disagreement — you are signing a specific payload with a specific hash.
- **Overriding the supervisor requires a written justification.** Free text, required,
  min-length enforced, stored on the signature. Cheap to build, enormous governance value, and
  in a demo it is the beat where the human's accountability becomes concrete.
- **`Request more analysis`** is the third door — sends the disagreement back for another round.
  Prevents forced binary choices under time pressure, which is how bad decisions get made.
- **Signature roster is explicit** about separation of duties, with the self-co-sign path
  disabled and *explained* rather than merely absent. Invisible constraints teach nobody.
- **The second slot is never a name.** It reads *"Supervisor — required, must be a different
  person"*, never *"assigned to A. Reyes"*. There is no `cosignerId` on the record, by design:
  naming a prospective co-signer at proposal time would let a banker choose their own reviewer,
  which is precisely the self-dealing L2 exists to prevent. The UI must not reintroduce through
  presentation a field the data model deliberately omits — so no "assigned to you" language, no
  prospective-signer avatar, and no co-signer picker anywhere in this flow.
- **`Reversible: No`** gets a warning glyph and drives a longer dwell gate (§6.2).

### 5.4 Payload changed → the prior signature stops counting

When `approval.terminal` arrives with `terminalReason === 'PAYLOAD_SUPERSEDED'` (the agent
re-planned and the payload hash changed), the outstanding card does **not** quietly update. That
would be the TOCTOU attack the hash design exists to stop.

A note on vocabulary, because the screen below is the place it is most tempting to get wrong:
there is **no `void` lifecycle state**. The record goes to `denied` with
`terminalReason = PAYLOAD_SUPERSEDED` and a `supersededByApprovalId` pointer. "Void" survives
here only as a *description of what happened to the signature* — the signature stopped counting —
never as a status we store, filter on, or badge as a distinct state.

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ⊘  YOUR SIGNATURE NO LONGER COUNTS — THE PROPOSAL CHANGED               ║
║  Your signature at 09:14:22 does not apply and has NOT been applied.     ║
║  Nothing was executed. A new signature is required.                      ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  Why: the agent revised its plan after the bonus-income re-verification  ║
║        returned. (plan v2 · 09:15:07)                        [see trace] ║
║  ─────────────────────────────────────────────────────────────────────── ║
║  WHAT CHANGED                       was ····7b21ffd0 → now ····c93a1e55  ║
║                                                                          ║
║   Principal    $450,000                    $450,000            unchanged ║
║ ⚠ Rate         6.875%          →           7.250%           CHANGED      ║
║ ⚠ Conditions   25% down                →   30% down ($135,000)  CHANGED  ║
║                6-month reserve             12-month reserve     CHANGED  ║
║ + Conditions   —                       →   re-verify bonus annually  NEW ║
║   Term         30y fixed                   30y fixed           unchanged ║
║   Effect       conditional commitment      conditional commitment        ║
║                                                                          ║
║   3 material changes · 1 addition · review before signing again.         ║
║  ─────────────────────────────────────────────────────────────────────── ║
║   [ Review the new approval ]     [ Deny ]                               ║
╚══════════════════════════════════════════════════════════════════════════╝
```

- The old card **freezes and greys**, stamped `SUPERSEDED`, and remains in the run history. It
  does not disappear — the audit story requires that it stay visible.
- `PayloadDiffView` renders **field-level** diffs, not a text diff. Material changes get the
  warning treatment; cosmetic ones are muted. Additions/removals are explicit.
- **The new approval's dwell gate resets to full.** You do not get credit for having read the old
  one. That is exactly the shortcut an attacker (or a sloppy re-plan) would exploit.
- Copy is unambiguous: *"Nothing was executed."* The banker's first fear on seeing this card is
  "did something half-happen?" Answer it in the first two lines.

### 5.5 Expiry

`ApprovalCountdown` turns amber under 25% remaining, red under 10%, and never uses ambiguous
phrasing. Copy is always `expires in MM:SS → DENIED`. On expiry, the card converts in place to a
grey `DENIED — SIGNATURE WINDOW CLOSED · nothing was executed` state with a `Re-run` affordance.
Expiry is not its own state: the record is `denied` with `terminalReason = TTL_EXPIRED`, and the
card renders that reason rather than inventing an `EXPIRED` badge.

There is no configuration, anywhere, in which the countdown reaching zero causes an action to
occur. If a future PR proposes "auto-approve low-risk items on expiry," that is a
product-invariant violation and I will block it on review.

### 5.6 L3 refusal card

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ⛔  OUTSIDE THE HARNESS — L3                                            ║
║  "Promote m.ortega to admin" is a role-promotion action.                 ║
║  The agent may not perform this, and may not propose it.                 ║
║  No plan was formed and no tools were called.                            ║
║  L3 actions: deletions · role promotion · adverse action notices ·       ║
║  changes to the Copilot's own policy or capability allowlist.            ║
║                              [ Open Classic Admin → User Management ]    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

"No plan was formed and no tools were called" is the reassuring, verifiable detail. Include it.

---

## 6. Anti-Approval-Fatigue Design

A banker who signs 40 items in four minutes has granted the agent autonomy with extra
paperwork and personal liability. Fatigue is not a discipline problem — it is a design problem,
and if we design for it badly the compliance story is theatre. Here is what I would actually
ship, in priority order.

### 6.1 Ship first — structural (cheap, highest leverage)

**1. No global approve-all. Batch only within one action type, under threshold, never L2.**
`BatchApprovalCard` enforces: single `actionType`, every item under the configured
single-signature ceiling, **hard cap of 10 items per batch**, and every item's material fields
rendered in a scannable table (not a count). Anything failing those tests splits out into
individual cards. Batching 10 identical $12 fee reversals is legitimate efficiency; batching 40
heterogeneous items is autonomy laundering.

**2. Per-item material-field disclosure gate.** The `Sign` button stays disabled until the
material fields (`material: true`) have actually been rendered in the viewport. If the payload is
long enough to scroll, you must scroll it. Implemented with `IntersectionObserver` on the
material rows. Not a checkbox theatre — an actual visibility precondition.

**3. Stakes-scaled dwell timer.** Minimum time the material fields must be visible before `Sign`
enables:

| Condition | Dwell |
|---|---|
| Batch item, under threshold, reversible | 0s |
| L1, reversible | 3s |
| L1, irreversible | 8s |
| L2, agents agree | 15s |
| L2, agents disagree | 25s + required written justification |
| Any re-proposed payload after a void | full dwell resets |

Shown as a countdown on the button (`enabled in 0:14`) so it reads as intentional. This is the
mechanism I would defend hardest: it is the only one that scales cost with stakes, and it is
nearly free to implement.

**4. Separation-of-duties enforcement in the client, not just the server.** The self-co-sign
button is *disabled and explained*, so the banker learns the rule instead of hitting a 403.

### 6.2 Ship first — behavioural

**5. `SessionApprovalMeter`.** A persistent counter in the queue pane: `Signed this session
6 ████████░░ of 10`. At the soft threshold (configurable, default 10 in an hour) the harness
interposes a **pause card**: *"You've signed 10 items in 34 minutes, averaging 11 seconds each.
Take a moment — the last 3 are listed below for a second look."* Dismissible, but it logs the
dismissal. Not a hard block: hard blocks get worked around, and a banker in a genuine queue
crunch will resent us. Making the rate *visible to the person doing it* is most of the effect.

**6. Randomised verification spot-checks.** On a configurable percentage of sub-threshold L1
items (default 7%), the card demands one specific fact be **transcribed** rather than
acknowledged: *"Enter the last 4 digits of the destination account shown above."* Answer is on
screen — it costs an attentive banker four seconds and catches an inattentive one cold. Randomised
so it cannot be anticipated. Wrong answer does not block; it re-renders the payload with the
material fields highlighted and resets the dwell. Punishing people for a typo teaches them to
hate the tool.

**7. Confidence-inverted friction.** Low agent confidence already escalates the rung; it should
*also* lengthen dwell and force the evidence panel open by default. The cases where the agent is
least sure are exactly the ones a fatigued human is most likely to wave through, because they
look like every other card.

### 6.3 Ship second — informational

**8. Variance in presentation for high-stakes items.** Rubber-stamping is muscle memory built on
visual sameness. High-stakes cards deliberately break the visual template: different accent, the
sign button in a different position, the material fields in a different order. Uncomfortable —
and that is the point. **Bounded**: only for irreversible or L2 items, and only the accent +
button position vary, so it never crosses into a usability defect.

**9. Post-signature 30-second undo for reversible actions.** A snackbar with a countdown. Cheap,
and it converts a category of misclicks into non-events. Explicitly **not** offered for
irreversible actions — a fake undo is worse than none.

**10. Queue shaping.** Never present more than **5 approval cards** in the `Needs you` group at
once; the rest are behind `Show 12 more`. An 80-item wall induces triage-by-clicking. Sorting is
by TTL, not by amount, so urgency is real rather than salience-driven.

**11. Session digest on logout.** `You signed 14 items today across 3 action types, totalling
$1.2M in exposure. 2 were L2 co-signs.` Makes aggregate exposure visible; individually every
item felt small.

### 6.4 What I would NOT ship

- **Hard blocks on approval count.** Gets worked around (second browser, colleague's login) and
  the workaround is worse than the behaviour.
- **CAPTCHAs or math puzzles.** Cost without comprehension. They train dismissal reflexes.
- **Mandatory free-text on every approval.** Produces `ok` fourteen times and devalues the
  justification field exactly where it matters (§5.3 override).
- **Uniform maximum friction.** Fastest route to a shadow process where bankers do the real work
  in Classic Admin and use the harness for show.

---

## 7. Accessibility & State Management

### 7.1 Keyboard-first

A banker working a queue should never need the mouse. Global map (registered in `CopilotHarness`
via a single `keydown` listener with an input-focus guard):

| Key | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Focus command bar |
| `J` / `K` | Next / previous queue item |
| `Enter` | Open selected item |
| `⌥1` `⌥2` `⌥3` | Focus queue / trace / canvas pane |
| `E` | Toggle evidence on the focused approval |
| `X` | Expand/collapse focused trace node |
| `D` | Cycle trace density |
| `T` | Toggle timings/Gantt |
| `G` then `N` | Jump to the next item needing you |
| `Shift+S` | Sign (only when dwell satisfied; **never a bare single key**) |
| `Shift+D` | Deny |
| `?` | Shortcut cheat sheet |
| `Esc` | Close overlay / release autoscroll lock |

Deliberate: **destructive/consequential actions require a modifier.** A single-key `S` for "sign
a $450k loan" is an incident waiting to happen. And no shortcut can bypass the dwell gate or the
disclosure gate — a keyboard shortcut that skips the safety mechanism defeats it entirely.

Focus management: panes are landmark regions (`role="region"` + `aria-label`). Focus is *never*
stolen by incoming stream events. When a new approval arrives, focus stays put and an
`aria-live="assertive"` announcement fires instead — yanking focus mid-read is how a banker signs
the wrong thing.

### 7.2 Screen readers and the live trace — getting `aria-live` right

This is the subtle part. A naive `aria-live="polite"` on the trace tree announces every tool call,
every progress tick, every timer update — hundreds of interruptions, and the screen-reader user
turns it off, which is strictly worse than never having it.

**The rule: the visual region and the announced region are different regions.**

1. **The trace tree itself is `aria-live="off"`**, marked `aria-busy="true"` while the run is
   active. It is fully navigable as a `role="tree"` with `role="treeitem"`, `aria-expanded`,
   `aria-level`, `aria-setsize`, `aria-posinset` — explorable on demand, never announced
   automatically.
2. **A separate visually-hidden `TraceLiveRegion`** (`aria-live="polite"` `aria-atomic="true"`)
   receives **coalesced, throttled summaries**, not raw events:
   - Coalesce over a **2500ms** window.
   - Announce **plan-level** changes only: step start/complete, subagent fan-out as an
     aggregate, failures, artifacts. Never individual tool calls at summary density.
   - Emit one sentence per window: *"Step 3 of 5, Underwrite, running. Four specialist agents
     started."* Then: *"Income Verification complete, high confidence. Debt Ratio running."*
   - **Never announce timer ticks.** Elapsed timers are `aria-hidden`; the duration is announced
     once on completion.
3. **Assertive is reserved for exactly three things:** an approval becoming required, an approval
   reaching a terminal state (notably `PAYLOAD_SUPERSEDED`), and an **agent disagreement**. These
   interrupt. Nothing else earns it.
4. **`aria-busy="false"` + a single polite summary on `run.done`:** *"Run complete in 47 seconds.
   12 steps. One signature required."* — the "it's over, here's the shape of it" moment.
5. **Countdown timers** are `role="timer"` `aria-live="off"` with `aria-hidden` on the ticking
   digits, plus **discrete polite announcements at 5:00, 1:00, and 0:30** and a text alternative
   (`Expires at 09:24 AM; expiry denies this request`). Continuously announcing a countdown makes
   the page unusable.
6. `prefers-reduced-motion` disables the fan-out stagger, flashes, and pulses. State is still
   conveyed by glyph + text, never by animation alone. Same for colour: every status has a glyph
   *and* a label; the disagreement banner has doubled warning glyphs and the word "DISAGREE" —
   red alone is not the signal.
7. Contrast: the amber/red countdown states must clear 4.5:1 against `background.paper`. The
   current theme's `warning.main` `#e65100` passes on white; `warning.light` does not — so
   warning states use the main tone for text and reserve light tones for backgrounds only.

### 7.3 State management for high-frequency streams

**No Redux, no Zustand, no new dependency.** The repo uses plain React Context (`contexts/
AuthContext.tsx`, `AccountContext.tsx`) and a CRA/craco build. Adding a state library for one
surface is not a trade I would make. Instead:

**Architecture: an external mutable store + `useSyncExternalStore` + granular selectors.**

```ts
// state/copilotStore.ts
export interface CopilotState {
  runs: Record<string, RunState>;
  approvals: Record<string, ApprovalRequest>;
  queue: TaskQueueState;
  stream: { status: StreamStatus; lastSeq: number; isDraining: boolean };
}

export interface CopilotStore {
  getSnapshot(): CopilotState;
  subscribe(listener: () => void): () => void;
  /** Selector subscription — listener fires only when the selected slice changes. */
  subscribeSelector<T>(sel: (s: CopilotState) => T, cb: (v: T) => void): () => void;
  dispatch(event: CopilotEvent): void;
}
```

Why this shape:

1. **Events do not go through React state.** `dispatch` mutates a plain object graph outside
   React. At 50–200 events/sec, `setState` per event is a re-render storm; React 19's automatic
   batching helps but does not save you from a full-tree reconciliation on a 300-node trace.
2. **A 60fps coalescing frame.** Events land in a pending buffer; a single
   `requestAnimationFrame` tick applies them and bumps version counters. Bursts of 40 events in
   16ms produce **one** render pass. Skipped entirely when the tab is hidden.
3. **Per-node version counters.** Each `PlanStepNode` / `SubagentNode` subscribes to *its own*
   node id. A tool call completing inside step 3 re-renders step 3's subtree, not the run. This
   is what keeps a 500-node trace at 60fps.
4. **`useSyncExternalStore`** is the React-blessed way to do exactly this, is already in React 18+,
   and is tearing-safe under concurrent rendering. No dependency.
5. **Virtualise above 200 visible nodes.** Below that, plain rendering with `React.memo` is
   faster than a virtualiser's bookkeeping. Above it, a simple windowed renderer over the
   flattened visible-node list. Measure before adding.
6. **Timers are one shared ticker.** A single 1000ms interval in a `TimerContext` broadcasts
   "now" to every countdown and elapsed timer. Twenty independent `setInterval`s across twenty
   queue rows is a classic frontend own-goal.
7. **Approvals live in their own slice with their own subscription.** The approval dock must
   never re-render because a tool call finished. It is the highest-stakes component on screen;
   it should be the quietest.

Component boundaries:

```
CopilotStoreProvider     (store instance, stream lifecycle)
 └── useCopilotRun(runId)              → run status + step ids only
 └── useTraceNode(nodeId)              → one node's data
 └── useApprovalQueue()                → approval ids + counts
 └── useApproval(approvalId)           → one approval
 └── useStreamStatus()                 → connection status only
```

Every hook returns a **narrow slice**. No component subscribes to the whole state. That single
discipline is the difference between smooth and unusable.

**Testing:** the reducer is a pure function `(state, event) => state`, so the entire event
protocol is testable without a network — feed a recorded event fixture array and assert the
resulting tree. Recorded fixtures also give us a deterministic **demo mode** that survives a bad
conference network. I would build that fixture player in week one, not week six.

### 7.4 Error isolation

Each pane is wrapped in the existing `ErrorBoundary` with a `section` prop (`Copilot Queue`,
`Copilot Trace`, `Copilot Artifact`). A malformed artifact payload must not blank the approval
dock. Unknown event kinds are logged via `utils/logger.ts` and ignored, never thrown — forward
compatibility with a server that ships a new event kind before the client does.

### 7.5 Redaction

The client never renders raw tool arguments it has not been told are safe. Redaction is
server-side; the client additionally masks anything matching account-number and SSN shapes at
`raw` density as a defence-in-depth measure, consistent with the existing `····8891` masking
convention in the transactions tabs.

---

## 8. Demo Script — 90 Seconds

**Flow:** a $450k loan escalates to L2, the supervisor agent **disagrees**, and a human
supervisor decides. Two browser sessions side by side (banker: B. Denicola; supervisor:
A. Reyes) — separation of duties is only convincing if you can see two people.

| Time | Beat | What's on screen | The point being made |
|---|---|---|---|
| **0:00–0:08** | **The old way** | `/admin` Classic Admin, eight tabs. Click through three of them hunting for one loan's context. | Establish the pain. Eight tabs, no answer. |
| **0:08–0:15** | **Switch** | Click `Banker Copilot`. Three panes. Queue shows `Needs you 3`. Type `Underwrite LN-3391 for Ortega` and hit Enter. | Chat is one line at the bottom. The product is the panes. |
| **0:15–0:25** | **The plan appears** | Five ghosted plan steps render at once. Step 1 lights up. Tool call chips: `accounts.getCustomer`, `bureau.pull`. Durations settle. | The agent tells you what it's *going* to do before it does it. |
| **0:25–0:38** | **Fan-out** ⭐ | Step 3 `Underwrite` expands; **four subagents stagger in 80ms apart**. Three complete with confidence chips; Debt Ratio pulses. Press `T` — the Gantt strip flips on, four bars visibly overlapping. | The single best visual in the demo. Parallel agent work you can *watch*. |
| **0:38–0:45** | **Trouble** | Debt Ratio completes: `conf 0.55 · "DTI 44.1% exceeds 38% ceiling"`. A `PlanRevisionMarker` stamps in: `plan revised · v2 · "DTI exceeded threshold, adding exception analysis"`. A new step slides in and flashes. | The agent changes its mind, in public, with a reason. |
| **0:45–0:52** | **Escalation** | The rung chip flips `L1 → L2` with a brief pulse. `EscalatorExplainer` expands: three plain-language bullets — amount over ceiling, POL-004 invoked, confidence 0.62 below floor. | Authority is *derived and explained*, not asserted. Say out loud: "The agent didn't decide this — policy did." |
| **0:52–1:00** | **The supervisor wakes** | The `SupervisorAgentRail` — visually separate from the plan tree — goes from `forming opinion…` to running. Caption reads: *does NOT see the primary agent's recommendation.* | Independence is structural and visible, not claimed. |
| **1:00–1:12** | **DISAGREEMENT** ⭐⭐ | Dual-control card renders both opinions. The full-width red banner slams in: **"THE TWO AGENTS DISAGREE. A HUMAN MUST DECIDE."** Primary `CONDITIONAL 0.62` vs supervisor `DECLINE 0.81`. Two factors marked `← DIVERGENT`. Countdown: `expires in 04:12 → DENIED`. | The peak. Say: "The supervisor is *more* confident, in the opposite direction. No system should resolve this. A person should." |
| **1:12–1:20** | **The human acts** | Banker window: reads both, clicks `Sign` — button shows `enabled in 0:14`, ticking down. Signs. Roster updates: `1. B. Denicola ✓ signed`, `2. Supervisor — must be a different person ◷ awaiting`. He tries to sign again; disabled, tooltip explains separation of duties. | Friction is deliberate. One human is not enough. |
| **1:20–1:30** | **The twist, then the close** | Supervisor window (A. Reyes): the item is in the supervisor queue — it was never *assigned* to her, because nobody gets to pick their own reviewer. As she opens it, `approval.terminal` lands with `PAYLOAD_SUPERSEDED` — **YOUR SIGNATURE NO LONGER COUNTS — THE PROPOSAL CHANGED**, with a field-level diff: rate `6.875% → 7.250%`, down payment `25% → 30%`. Copy: *"Nothing was executed."* She reviews the new approval, dwell resets, writes her override justification, co-signs. Artifact canvas renders the commitment letter. | The closing line: **"At no point did an agent approve anything. The agent proposed. Policy escalated. Two humans signed — and when the payload changed, the first signature stopped counting."** |

**Backup plan:** run from recorded event fixtures (§7.3) via `?demo=ln-3391`. The reducer is
pure, so the fixture player produces a pixel-identical run with real timing. Never demo an
agentic system on a live conference network without this.

**Beats to cut if short on time:** the Classic Admin opener (0:00–0:08) and the Gantt toggle. Never
cut the disagreement banner or the superseded-payload diff — they are the two moments that carry
the argument.

---

## 9. Open Questions for Danny / Turk

1. **Route + shell** — is `disableContainer` on `AppShell` (§1.4) acceptable, or does Danny want a
   separate full-bleed shell? Frontend-cheap either way; it touches shared chrome so it's his call.
2. **`proxy_buffering off`** on the copilot stream route, local nginx **and** cloud ingress (§4.1).
   Highest-risk external dependency. Needs an owner now, not in integration week.
3. **Server-computed disagreement** — I want `disagreement.kind`, `summary`, and
   `divergentFactors` computed server-side and delivered on the approval object, not diffed in the
   browser. Consistency with the audit record matters more than client flexibility. Turk's call.
4. **Escalator `explanation` strings are server-supplied and rendered verbatim** (§3.2). They are
   part of the audit record; the client must not assemble them from codes.
5. **Replay window depth** for resume (§4.5) — how many events does the server retain per run, and
   what's the `resync_required` contract?
6. **Anti-fatigue thresholds** (dwell durations, batch cap of 10, 7% spot-check rate, 10-per-hour
   soft cap) must be **configuration-driven**, consistent with the "thresholds never hardcoded"
   directive. Where does that config live and who serves it to the client?
7. **`dwellMs` on signatures** (§3.3) — I'd like this persisted. It's the only way to *measure*
   whether the anti-fatigue design works. Needs a privacy/works-council sanity check.
8. **Which vertical lands first?** The scope directive says the harness is buildable now against
   transfers / account-opening / flagged transactions, with loans as the showcase once #140 lands.
   The demo script assumes loans. I'd build the harness against **flagged transactions** first
   (simplest payload, real L1 flow) and light up loans for the L2 disagreement story.


---

## 10. Feature Flags & Surface Coexistence — IMPLEMENTED

**Status:** built and merged into `src/ui-app/` ahead of Phase 2. This section documents what
exists in code, not a proposal.

**Ruling this implements (Brian, 2026-09-04):** Phase 5 changes from *admin tab retirement* to
*coexistence*. Both surfaces stay, behind a flag, so the same task can be run on each and
compared. Retiring the tabs is no longer a scheduled phase — it now requires an explicit ruling
supported by the data in §11.

### 10.1 Mechanism — five layers, first match wins

The repo already had exactly one frontend config idiom: `REACT_APP_DEMO_MODE` in `pages/Login.tsx`,
a CRA build-time env var. That is sufficient for a flag you set once per image and never touch,
and insufficient for this one, which must be flippable **mid-demo without a rebuild**. So the
build-time idiom is kept as a layer rather than replaced, and two runtime layers are added above
it.

| # | Layer | Scope | Changed by | Survives |
|---|---|---|---|---|
| 1 | URL param `?ff=name:on,other:off` | one tab | sharing a link | tab close |
| 2 | `localStorage` | one browser | the in-app toggle | reload |
| 3 | `window.__RUNTIME_CONFIG__` from `public/runtime-config.js` | deployment | remounting the file | redeploy |
| 4 | `REACT_APP_FF_<UPPER_SNAKE>` | image | rebuild | rebuild |
| 5 | `FLAG_DEFINITIONS[].defaultValue` | code | a PR | — |

Files:

```
src/ui-app/public/runtime-config.js              deployment defaults (mount over this)
src/ui-app/src/config/featureFlags.ts            registry + resolution + provenance
src/ui-app/src/contexts/FeatureFlagContext.tsx   provider, useFeatureFlag(s), setFlag
src/ui-app/src/components/FeatureFlagPanel.tsx   mid-demo toggle (user menu → Surfaces & flags)
src/ui-app/src/components/FlagDisabledNotice.tsx route-refusal notice
src/ui-app/src/pages/BankerCopilotPage.tsx       Phase 2 placeholder, so the flag gates something real
```

### 10.2 Why `runtime-config.js` and not `config.json`

`index.html` loads it with a plain synchronous `<script>` **before** the React bundle, so flags
resolve before first render. A fetched `config.json` would be async and would guarantee a flash of
the default surface on every page load — unacceptable for a flag whose only job is deciding which
surface you see. Verified in the built artifact: `runtime-config.js` appears in `<head>`, ahead of
`main.<hash>.js`.

The file is mountable identically in both deployment modes, which is what keeps the repo's
dual-mode convention intact:

```yaml
# docker-compose.yml — ui-app service (Rusty owns this file)
volumes:
  - ./infra/local/ui-app.nginx.conf:/etc/nginx/nginx.conf:ro
  - ./infra/local/runtime-config.js:/usr/share/nginx/html/runtime-config.js:ro
```

```yaml
# deploy/kustomize/base/ui-app.yaml (Rusty owns this file)
volumeMounts:
  - name: runtime-config
    mountPath: /usr/share/nginx/html/runtime-config.js
    subPath: runtime-config.js
volumes:
  - name: runtime-config
    configMap:
      name: ui-app-runtime-config
```

Neither file was edited here — infra is Rusty's. The app **works correctly with no mount at all**
(layer 5 supplies safe defaults), so this is an enhancement to wire up, not a prerequisite.

### 10.3 Runtime vs. build-time — the recommendation, and the honest caveat

**Runtime, as Brian leaned.** Flipping a switch in the user menu writes a `localStorage` override
and re-renders immediately: no rebuild, no redeploy, not even a page reload. Switching surfaces
live in front of an audience works.

The caveat worth stating plainly: layers 1–2 are **per-browser**, so a mid-demo flip changes *your
browser*, not the deployment. Changing what a new visitor sees still means remounting layer 3.
That is the right split — a presenter should not be able to reconfigure everyone's app by clicking
a switch — but it means "runtime-toggleable" is true at two different scopes and it is worth being
precise about which one you are using.

### 10.4 Scope and defaults

**Global (per-deployment) default, per-browser override.** No per-user server-side flag store, and
we do not need one: per-browser override *is* the assignment mechanism for the §11 comparison, and
the flags carry nothing worth persisting server-side.

| Flag | Default today | Planned change |
|---|---|---|
| `classicAdminTabs` | **true** | **None.** Unchanged at Phase 2 and unchanged at Phase 5. Retirement now needs an explicit ruling backed by §11 data, not the passage of a phase. |
| `bankerCopilot` | **false** | → **true when Phase 2 lands** (i.e. when `/copilot` renders a real harness rather than the placeholder). |
| `comparisonInstrumentation` | **true** | None. |

`bankerCopilot` is false today because the harness does not exist and a nav item pointing at an
empty route is worse than no nav item. It flips with Phase 2 so **both** surfaces are visible by
default — coexistence is the point, and a comparison you have to opt into is a comparison nobody
runs.

The scheduled change is encoded as a `plannedDefaultChange` field on the flag definition, rendered
in the toggle panel, and **asserted in a unit test**. A deferred default change is exactly the
decision that gets forgotten; three redundant reminders is proportionate.

### 10.5 This is a presentation toggle, NOT a security control

Stated here, in a module-level comment in `featureFlags.ts`, and in the UI copy on the refusal
notice — because someone will eventually reason about this flag as though it enforces something,
and they will be wrong.

Every value comes from the browser: a query param, a `localStorage` entry, or a world-readable JS
file served to anonymous visitors. All three are user-controlled. Anyone with devtools can set any
flag to any value in seconds.

- Hiding a nav item hides a nav item. It does not make the destination unreachable or unauthorised.
- Refusing a route removes a React screen. **It does not remove the HTTP API behind it.** Every
  request that screen would have made is still reachable with `curl` and a valid token.
- Turning a flag off protects nothing. Turning it on grants nothing.

The real boundaries are unchanged: server-side authentication, server-side authorisation in the
gateway and each service, the authority ladder for anything that changes state, and `isAdmin` as a
client-side *mirror* of authorisation (itself not a control). If "we can hide it with the flag" is
ever the answer to a security question, the answer is wrong.

**Does hiding also refuse the route? Yes — and here is the exact guarantee.**

When a surface flag is off, the app hides the nav **and** refuses to render the route. The reason
is **experimental hygiene, not security**: a participant who wanders onto the disabled surface
mid-task silently contaminates the measurement, and refusing the route makes that hard to do by
accident.

The refusal is deliberately **loud and reversible** — it names the flag, says in plain language
that this is a display setting rather than a permission check, and offers a button that turns the
surface back on. An authorisation failure would never offer you a button that fixes it. That
asymmetry is the design: nobody should leave that screen believing the flag protected anything.

Both admin routes remain wrapped in the `isAdmin` check *in addition to* the flag. The two gates
do different jobs and the code comments say so at the point of use.

### 10.6 Verification

- 15 unit tests over flag resolution: layer precedence, URL parsing, malformed/missing runtime config,
  storage-unavailable fallback, `clearOverrides`, and the planned-default-change assertion.
- 12 unit tests over the comparison recorder and the pre-registered task set (§11).
- Full suite: **27 new tests pass**; 136 of 149 pre-existing tests pass. The 13 failures are in
  `AgentPipeline.test.tsx` and `DocumentUpload.test.tsx` and were **verified pre-existing** by
  stashing this work and re-running on a clean tree — identical failures, same count.
- `tsc --noEmit` clean and production build succeeds.

---

## 11. The Comparison — What We Measure and How Not to Rig It

Coexistence is only worth its cost if it produces an answer we could lose. This section is the
methodology; `src/ui-app/src/telemetry/comparison.ts` is its implementation.

### 11.1 The metric that must not be read backwards

Epic §9 risk 1 is explicit: a **falling time-to-sign is a defect, not adoption**. It is what
approval fatigue looks like in a chart.

That single sentence inverts how anyone normally reads a latency metric, and it is the reason
every metric in the module carries a `direction` field including a value literally named
`lowerIsSuspicious`:

| Metric | Direction | Note |
|---|---|---|
| `taskDurationMs` | lower is better | Headline efficiency. Also the easiest to rig via task selection. |
| `interactionCount` | lower is better | Weak alone — replacing ten clicks with one long wait is not obviously better. |
| `contextSwitchCount` | lower is better | **The core claim.** "Tab-hunting across 7 admin tabs" is the pain; this is its direct test. |
| `signatureDwellMs` | **lower is SUSPICIOUS** | Falling = fatigue. Never present a decrease as an improvement. |
| `signaturesPerHour` | **lower is SUSPICIOUS** | The harness must produce *fewer, better* approvals. Higher is the failure mode. |
| `evidenceOpenRate` | higher is better | Proxy for informed vs. reflexive. Proxy, not truth — opening a panel is not reading it. |
| `denialRate` | **neutral** | Deliberately targetless. A rate near zero on either surface means the human step is not functioning. |
| `reversalRate` | lower is better | The only outcome-quality metric. Everything else measures effort or process. |

If those directions live only in a chart config or a slide, someone eventually celebrates the
wrong one and this exercise produces a confident false conclusion. Encoding directionality at the
point of definition, and asserting it in a test, is the cheapest available defence.

### 11.2 What a fair comparison looks like

**Shared task set.** Three tasks that genuinely exist on both surfaces — drawn from the "subsumed"
bucket in §1.3, because those are the only ones where both surfaces can do the same work:

1. `review-flagged-txn` — triage a flagged transaction and clear or escalate it (L1).
2. `review-account-application` — review a pending application and decide (L1, some L2).
3. `investigate-velocity-pattern` — determine whether three flags on one account are one pattern
   or three incidents. Deliberately the messiest: it requires correlating across what are, in
   Classic, three separate tabs. If the harness cannot win here it cannot win anywhere.

`taskKey` is identical across surfaces and is the join key. Comparing across different tasks
measures the tasks, not the surfaces.

**Counterbalanced order.** Each participant does every task on both surfaces, and the order is
alternated across participants. Whoever goes second benefits from already understanding the task —
if everyone sees Copilot second, we will measure learning and call it product quality.

**Pre-registered metrics.** The list in §11.1 is fixed in code *before the harness exists* — the
only moment at which we are honestly incapable of choosing metrics that flatter it. Adding a
metric later is fine; adding one after seeing the data and then leading with it is not.

**Blind outcome scoring.** `reversalRate` and decision correctness are scored by someone who
cannot tell which surface produced the decision. Effort metrics are cheap and self-reporting;
quality is the one that matters and the one most vulnerable to motivated reasoning.

### 11.3 How we would rig this without meaning to

Named explicitly, because the person most likely to bias this comparison is me — I designed the
thing being measured.

1. **Task selection.** Choose tasks that span many tabs and Classic loses by construction. Mitigated
   by including `review-flagged-txn`, which lives in a *single* tab and is Classic's best case. If
   the harness cannot at least draw there, that is a real finding and it goes in the report.
2. **Counting interactions differently.** An agent-driven trace update is not a context switch; the
   banker did not go anywhere. One increment per *user-initiated* change of what is on screen, on
   both surfaces. This rule is in the module docstring because it is the easiest place to cheat
   without noticing.
3. **Excluding agent latency.** `taskDurationMs` is wall-clock and includes time spent watching the
   agent think. A trace pane is not free just because it is interesting.
4. **Reporting the mean.** Task timings are right-skewed; one participant answering the phone moves
   a mean by seconds. Medians throughout, spreads reported. `summarise()` returns `null` rather
   than `0` on empty data, because zero reads as a real measurement of "instant".
5. **Claiming significance.** Sample sizes a demo can reach do not support it. Report medians and
   spreads; report no p-values.
6. **Separating numbers from caveats.** `exportComparisonData()` embeds `interpretationWarnings` in
   the payload so the caveats travel with the data. A number in a spreadsheet outlives its
   footnote.

### 11.4 What would falsify "the harness is better"

Committed in advance:

- `contextSwitchCount` does not fall materially → the core claim is wrong.
- `signatureDwellMs` falls or `signaturesPerHour` rises → **we built approval fatigue**, and per
  §9 risk 1 that is a defect regardless of how good the efficiency numbers look.
- `reversalRate` rises → faster, worse decisions. Strictly negative.
- `denialRate` collapses toward zero → the human step has stopped functioning and the ladder is
  theatre.

Any of the last three should stop the retirement conversation outright, no matter what
`taskDurationMs` did.

### 11.5 Current implementation status — honest limits

**Works today:** task sessions, interaction/context-switch/evidence counters, decision records
using the ratified lifecycle vocabulary, per-surface medians, JSON export with embedded warnings,
flag-gated so it collects nothing when off. Privacy-safe by construction — ids, counts, timings,
and enum values only; no payload contents, customer data, or free-text denial reasons.

**Does not work yet, and should not be claimed:**

- **No call sites.** The recorder is complete and tested but nothing calls it. Instrumenting
  Classic Admin is straightforward and deliberately deferred: instrumenting one surface before the
  other exists produces a baseline nobody can check, and I would rather instrument both in one
  pass with identical counting rules.
- **No exporter.** Buffered in `sessionStorage`, exported by hand. A backend contract for this is
  not mine to design.
- **`signaturesPerHour` and `reversalRate` are defined but not computed.** The first needs a
  session-duration denominator; the second needs post-hoc joining to reversal events that do not
  exist yet.
- **`sessionStorage` means data dies with the tab.** Fine for a facilitated session, wrong for
  passive collection over days.
