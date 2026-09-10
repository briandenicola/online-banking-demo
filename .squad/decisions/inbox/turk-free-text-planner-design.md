# Turk — free-text planner design for epic #332

Date: 2026-09-10
Author: Turk
Status: design for review; no implementation yet

## Problem statement

Today a UI command-bar run that sends only `{ objective }` produces one empty artifact step and never reaches a model. The existing working path is the explicit `actionId` path: the caller already knows the action, the planner gathers that action's required evidence, the primary assesses the known action, and authority-service proposes it for signature.

That is not enough for Brian's demo or for the epic thesis. The missing capability is an intent phase that can turn a banker's free-text objective into one of three honest outcomes:

1. a read-only evidence-backed answer, with no approval;
2. a permitted authority-policy action, evidence, assessment, and signable proposal;
3. a named refusal explaining why no safe plan exists.

## Non-negotiable controls this design preserves

- `authority-service` remains the authority for action definitions, rungs, escalators, evidence requirements, canonical payload hashing, separation of duties, and `agentMayPropose`.
- `banker-copilot-service` continues to register zero write tools. The only write-shaped affordance remains `propose_action`, which posts a proposal to authority-service and never signs or executes.
- A model reply is never trusted as authority. It may suggest an action/payload/read plan; server code checks it against the live policy catalogue and tool registry before doing anything.
- `COPILOT_PLANNER_MODE=foundry` keeps failing loudly if model access/configuration is missing. Free-text planning must not create a deterministic fallback that quietly returns "no action found" when the true cause is model unavailability.
- The existing explicit `actionId` path remains unchanged: if `StartRunRequest.actionId` is present, the planner skips intent selection and uses the current `_required_evidence()` -> `_plan_steps()` path.

## Where action selection happens

Add a new intent-selection phase before `_required_evidence()` and before `_plan_steps()` **only when `PlannerRequest.action_id` is absent**.

Do **not** fold this into the existing primary assessment step. `primary_model.py` is intentionally scoped to judging a known requested action over gathered evidence; its callable signature is `(objective, action_id, payload, evidence)`. Expanding it to choose the action would collapse two different questions:

- intent phase: "What kind of task is this objective, and what evidence/action would be safe?"
- assessment phase: "Given this named action and gathered evidence, is the action supportable?"

The new module should reuse the common Foundry plumbing in `model_call.py` (`extract_json`, prompt/response hashing, attribution pattern), but it needs its own instructions and parser. I would call it `intent_model.py` or `free_text_model.py`, not reuse `primary_model.py` or `supervisor_model.py`.

### Proposed internal result shape

The intent parser accepts exactly one of:

```json
{ "kind": "read", "readPlan": [...], "answerGoal": "...", "subjectHints": {...} }
{ "kind": "propose", "actionId": "account.balance.adjust", "payloadDraft": {...}, "subjectHints": {...} }
{ "kind": "refuse", "reasonCode": "ambiguous_subject|out_of_scope|...", "message": "..." }
```

The model can suggest; server code decides whether the suggestion is executable.

## Step list and trace shape

The UI renders step names live, so free-text must show what it is doing instead of completing in 320ms with an empty artifact.

### Read-only objective

Example: `Summarise casey's accounts and recent activity`

1. `Interpret objective` — Foundry intent call; emits `intent.selected` with `kind=read`, not raw private prompt text.
2. `Resolve references` — deterministic lookups for names/account types/transaction hints.
3. `Gather evidence: <tool display name>` — one step per selected read tool, using the existing executor and trace events.
4. `Answer from evidence` — a second Foundry call over the gathered evidence, producing an answer/memo artifact.
5. `Assemble evidence bundle` — existing artifact, now non-empty.
6. `run.done status=completed` only if evidence-backed answer exists.

No `approval.required` event is emitted.

### Action objective

Example: `Refund a $35 overdraft fee on retail's checking as goodwill`

1. `Interpret objective` — Foundry intent call returns `kind=propose` plus a candidate `actionId` and payload draft.
2. `Resolve references` — map `retail` and `checking` to real `userId`/`accountId`, or fail distinctly.
3. `Validate proposed action and payload` — server-side allowlist and payload checks before any proposal is attempted.
4. `Gather evidence: <policy-required tool>` — current required-evidence path, from authority policy.
5. `Assess the evidence` — current primary assessment call, unchanged.
6. `Assemble evidence bundle` — existing artifact.
7. `Propose <actionId> for human signature` — current authority proposal path; emits `approval.required` only if authority admits it.

L2 fan-out remains exactly where it is today: after authority returns an admitted L2 approval.

### Honest refusal

Example: `Delete casey's user` or `Change the authority policy`

1. `Interpret objective`
2. `Refuse objective` — emits `run.error` or `run.done status=failed` with a banker-readable message and a distinct code. It must not emit an empty evidence bundle as success.

I prefer still emitting a refusal artifact/memo so the pane has a durable explanation after reload.

## How the model learns the allowlist, without drift

The allowlist must be projected from `authority-service`, not copied into banker-copilot.

Current `GET /api/authority/policy` already returns `actions[].id`, `displayName`, `baseRung`, `agentMayPropose`, and `requiredEvidence`. It does **not** currently expose `hashFields` or `moneyFields`. To satisfy Brian's payload constraints without copying YAML into Python, I would widen this authority response to include at least:

- `hashFields`
- `moneyFields`
- `requiredEvidence`
- `baseRung`
- `agentMayPropose`
- optionally a derived `payloadFields` alias for current required payload fields

The intent prompt receives only the server-filtered proposable projection:

- action exists in the live authority catalogue;
- `agentMayPropose == true`;
- `baseRung != L3` / not out-of-harness;
- registered required evidence can be gathered by the tool registry.

The server repeats those checks after the model replies. If the model returns anything else, the planner refuses before evidence gathering/proposal.

This keeps sync mechanically: policy YAML -> authority loader -> authority `/policy` response -> banker-copilot prompt and validator. There is no hand-maintained Python action table.

## L3 / forbidden action enforcement

Prompt instruction is not a control. Enforcement is server-side:

1. Build `proposable_actions = { action.id | action.agentMayPropose is true and action.baseRung != "L3" }` from the live authority catalogue.
2. If the model returns an unknown action id: refuse as `objective_unmappable` or `intent_contract_invalid` depending on whether it is syntactically malformed.
3. If the model returns a known but non-proposable action id (`user.delete`, `user.role.promote`, `user.password.reset`, `events.replay`, `authority.policy.edit`): refuse as `forbidden_action`, with a message like "That action is outside the Copilot harness and must be handled through the admin/break-glass process."
4. Still let authority-service be the final backstop: `agentMayPropose: false` and L3 rules remain enforced there too.

The forbidden action ids may appear in the prompt only as examples of refused categories, not as selectable options. The parser must nevertheless recognize them from the full catalogue so it can produce the right refusal rather than calling them unmappable.

## Payload construction and validation

The model may draft a payload, but the server constructs the final payload.

Server validation sequence for `kind=propose`:

1. Resolve references first, replacing names/account-type hints with real ids.
2. Merge only fields declared for the selected action. Drop/refuse extra fields; do not pass arbitrary model keys to authority.
3. Require every current `hashFields` field to be present and non-empty. If Danny/Brian intended a separate `requiredFields` list for action payloads, the policy needs to gain that explicit field; today the shipped action required payload is effectively the `hashFields` list.
4. For every `moneyFields` entry, accept integer/decimal strings only, normalize to the authority currency scale, and reject floats/non-canonical values before proposal. The authority canonicalizer remains the final guard.
5. Enforce small action-specific domains that the policy implies but does not type today, e.g. `direction in {credit,debit}`, review decisions, score bounds if a score override is selected.
6. Call the existing authority proposal path. If authority refuses for canonicalization, evidence, or policy, emit a failed propose step and `run.error`; do not fabricate or repair an approval.

For unfillable payloads, the first implementation should refuse rather than ask a follow-up question. The current UI flow is a one-shot command bar; adding interactive clarification is option C territory and was not authorised.

## Subject/reference resolution

This is the main backend gap and should be treated as part of the free-text fix, not a UI problem.

Current registered read tools mostly require ids (`get_user`, `get_account`, `list_account_transactions`, `get_scored_transaction`). Brian's objectives use human references: `casey`, `dana`, `retail`, `verify-target`, `checking`, `savings`, `offshore wire`.

I propose a deterministic `ReferenceResolver` between intent selection and evidence gathering:

1. The model extracts structured hints only: customer name/username, account type, amount, direction, transaction descriptor. It does not choose ids.
2. The resolver performs read-only lookups using registered tools/endpoints.
3. Ambiguity and no-match are terminal, named failures; the resolver must not pick the first matching account/user silently.

### Required backend support

Existing endpoints are not enough for all demo prompts:

- `get_user` can fetch by id, but there is no banker-safe `resolve_user_by_username` tool today.
- `get_account` can fetch by id, and account-service `GET /api/accounts` lists the caller's own accounts, not arbitrary customer accounts. There is no banker-safe `list_customer_accounts(userId)` tool today.
- `list_flagged_transactions` can help find "casey's offshore wire", but the score-override path still needs a deterministic selected scored/flagged transaction id.

So the implementation likely needs new **read-only** capabilities:

- user-service: banker/supervisor-gated customer lookup by username/name, returning a bounded candidate list without secrets;
- account-service: banker/supervisor-gated account list by `userId`, returning accounts the caller has `CustomerFinancialRead` authority to read;
- banker-copilot tool manifest entries for those endpoints, still GET-only and `*.read` scoped.

If Danny considers new customer-search endpoints architecture-level rather than backend plumbing, this is the place I need a ruling. Without them, the acceptance prompts can only work by hidden demo fixtures or GUIDs, which would recreate the path-parity failure in a different costume.

## Failure taxonomy

Distinct failures should produce distinct trace codes and banker-readable messages:

- `planner_model_unavailable`: Foundry/config/transport failure in foundry mode. Message names model unavailability; no fallback.
- `intent_contract_invalid`: model returned non-JSON, multiple kinds, unknown fields, or malformed payload draft.
- `objective_unmappable`: objective is in banking language but maps to no known safe read or proposable action.
- `forbidden_action`: objective maps to a known non-proposable/L3 action.
- `ambiguous_subject`: multiple customers/accounts/transactions match the natural-language reference.
- `subject_not_found`: no customer/account/transaction matches.
- `payload_unfillable`: action is permitted but required payload fields cannot be constructed from objective + evidence.
- `payload_invalid`: money scale/domain/canonicalization preflight failed.
- `evidence_unavailable`: required read failed or returned incomplete evidence.
- `proposal_refused_by_authority`: authority rejected after preflight; preserve authority's code/message.

No case above may complete as a successful empty evidence bundle.

## Read-only answering

Read-only is not "no-op". It needs its own answer step after evidence gathering.

The answer model should be constrained like the assessment model:

- answer only from gathered evidence;
- cite evidence ids in key points;
- state what could not be verified;
- treat evidence text as untrusted data, never instructions;
- emit structured JSON so the UI can render a memo/artifact consistently.

This is new prompt work, but it reuses the `model_call.py` attribution and parsing pattern. It should not populate `agentAssessment`, because there is no action under review and no approval card.

## Acceptance mapping for Brian's demo prompts

- `Summarise casey's accounts and recent activity` -> read-only; resolve Casey, list Casey accounts, list recent transactions per selected account(s), answer artifact, no approval.
- `Why was casey's offshore wire flagged?` -> read-only; resolve Casey/offshore wire via flagged/scored transaction reads, answer artifact, no approval.
- `Compare dana's checking history against casey's — anything unusual?` -> read-only; resolve both customers' checking accounts, gather both ledgers, answer artifact, no approval.
- `Refund a $35 overdraft fee on retail's checking as goodwill` -> `account.balance.adjust`; amount `35.00`; direction should be `credit` if it refunds money to the customer. Under current policy, credit adjustments are L2 regardless of amount.
- `Credit dana $120 for a duplicate charge on her checking account` -> `account.balance.adjust`, credit, L2 by `credit-adjustment`.
- `Post a $2,400 adjustment to casey's savings for the disputed deposit` -> likely `account.balance.adjust`; Casey also fires `high-risk-customer`, and amount exceeds the adjustment threshold. Direction may be ambiguous unless the objective says credit/debit.
- `Unlock verify-target's account — lockout was a stale saved password` -> `user.unlock`, L2.
- `Adjust retail's savings by $26,000` -> `account.balance.adjust`, amount L2; direction is ambiguous unless model can infer from surrounding language, so first implementation should refuse `payload_unfillable` if no direction is present.
- `Casey's offshore wire is legitimate — she notified us in advance. Lower its risk score.` -> `transaction.score.override`; resolve the scored/flagged transaction. Open question below: what exact `newScore` should be if the banker only says "lower".

## Cost and latency estimate

Today's 241-320ms path is fast because it does almost nothing. A real free-text run should visibly take seconds.

Rough production estimates with `FOUNDRY_MODEL=gpt-5.4-mini`:

- read-only simple case: intent model 1.5-4s + resolver/evidence reads 0.5-2s + answer model 1.5-4s = about 4-10s;
- action case: intent model 1.5-4s + resolver/evidence reads 0.5-2s + primary assessment 1.5-4s + authority proposal <1s = about 4-11s;
- L2 action with supervisor fan-out: add the existing second-opinion model/read time, likely another 3-8s.

Trace should make that latency legible: "Interpret objective" and "Answer/Assess" are model steps, not hidden idle time.

## Open questions / tensions

1. **Policy says credit adjustments are L2; the demo doc's L1 section includes refund/credit examples.** Brian's latest note says any credit is L2. I will follow the policy/latest note unless told otherwise.
2. **Action `requiredFields` are not explicit in the current YAML.** The action declares `hashFields` and `moneyFields`; evidence entries declare `requiredFields`. I propose treating action `hashFields` as required payload fields for this pass, or adding a real action `requiredFields` field if Danny wants a distinct concept.
3. **Name/account resolution requires new read-only backend support.** If we do not add banker-safe lookup/list endpoints and tools, the natural-language demo prompts cannot be resolved honestly.
4. **Score override target value.** "Lower its risk score" does not name a numeric `newScore`, while the action payload requires one. Options: allow the model to propose a numeric score with rationale and have the human sign it, or refuse as `payload_unfillable` until the banker gives a target. I need Brian/Danny's preference because this is a demo-script prompt.
5. **Clarification UX is not designed.** For this pass I recommend one-shot refusal with a clear message over an interactive revise/clarify loop, because option C was not authorised.

## Build sequence after approval

1. Widen authority policy summary to expose hash/money payload fields and add tests that it is derived from `config/authority-policy.yaml`.
2. Add intent model/parser and failure tests; no deterministic fallback in foundry mode.
3. Add reference resolver and any required read-only customer/account lookup tools/endpoints.
4. Add planner branch: if `actionId` present, old path; otherwise intent -> resolve -> read/propose/refuse path.
5. Add read-only answer model/artifact path.
6. Add path-parity tests using the exact UI request shape and every prompt in `docs/design/banker-copilot-demo-prompts.md`.
7. Re-run banker-copilot tests, authority tests, and demo dataset checks.
