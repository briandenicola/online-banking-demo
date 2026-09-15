---
date: 2026-09-15
author: Danny
status: proposed
component: banker-copilot-service/app/planner/primary_model.py, banker-copilot-service/app/planner/supervisor_model.py
issue: 370
---

# Keep planner instruction contracts separate and structurally first

## Decision

**keep as-is** Do not merge the primary and supervisor instruction constants, and do not
add a decorative configuration or injection seam for prompt customization. The two constants
are safety-contract surface, not generic prompt copy. No genuine present customization seam was
found that has an owner, a bounded input, or a deployment requirement.

## Safety-load-bearing contract

The primary contract is responsible for:

- judging the **requested action**, rather than repeating the banker's objective or inferring a
  different action;
- treating evidence, payloads, and the banker's words as untrusted data, including customer
  text that attempts to address the model or grant permission;
- preserving adverse-action semantics, so `proceed` means carry out the named restrictive action
  when that is the action under review;
- requiring a single structured JSON response with the fixed verdict, rationale, evidence-linked
  factors, unverified items, and read-only requested-evidence shape; and
- keeping the primary's evidence references honest: a citation to evidence not actually supplied
  is a contract violation and must be rejected.

The supervisor contract is responsible for:

- making the reviewer independent: it did not propose the action and has no access to the
  primary's reasoning, plan, or recommendation;
- applying the same untrusted-data boundary and action anchoring to evidence gathered by its own
  reads;
- preserving the same explicit adverse-action interpretation;
- requiring a single structured JSON second opinion with a counter-argument, rather than free-form
  approval text; and
- maintaining role asymmetry. The supervisor is a second opinion, not a second copy of the
  primary question.

These contracts are reinforced outside the constants. The modules have separate prompt builders,
the supervisor is constructed blind from `(spawn, own_evidence)`, and neither module imports the
other. Both builders serialize dynamic values as fenced JSON and label them as untrusted data;
that structure is the prompt-injection control and must not be replaced by prose interpolation.
The existing fail-closed parsing and structural tests remain part of the boundary.

## Deployment-variable aspects

The deployment can already vary execution mode, model endpoint and deployment, and model-call
timeouts through explicit configuration seams. Those variables select and bound the model call;
they are not a reason to make the safety instructions deployment-editable. The inspected
contracts contain no present requirement for tenant wording, locale text, feature flags, or
operator-supplied instructions. Adding an environment variable or caller-provided suffix now
would create the appearance of supported customization without an accountable use case or a
defined safety budget.

## Rejected seam

Reject a shared merge helper, arbitrary caller/environment instruction input, or a toggle that
only makes prompt text look configurable. Such a seam would make ordering and authority
ambiguous, invite safety text to be overridden or displaced, and risk erasing the primary/
supervisor independence guarantee. It would also preserve no meaningful product capability: the
only demonstrated need is already served by the existing deployment configuration outside the
prompt.

## Only acceptable future seam

If a concrete, owned requirement later demands situational wording, the only acceptable shape is
a fixed safety preamble that is structurally first and cannot be replaced, followed by a bounded,
audited situational suffix. The suffix must be treated as data, have an explicit schema and size
limit, fail loudly when invalid, and be assembled separately for the primary and supervisor so
their questions remain distinct. Tests must assert the exact client-bound prompt ordering and
prove hostile suffix content cannot displace or rewrite the fixed preamble, action anchoring,
untrusted-data boundary, adverse-action semantics, output contract, fail-closed guidance, or
role-specific asymmetry.

Any such future seam must preserve the current fenced JSON representation and structural
injection controls. It must not pass the primary's assessment into the supervisor or turn either
contract into a free-form instruction channel. Until that concrete requirement exists, keep both
instruction constants separate and byte-stable.

## Follow-up

None for this spike. No application, README, test, or existing decision record changes are
required.
