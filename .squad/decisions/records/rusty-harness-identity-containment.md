---
date: 2026-09-04
author: Rusty (Platform/Infra)
status: proposed
component: epic/banker-copilot
issue: 332, 334, 336
---

# The harness's containment is an IAM boundary, not a code convention

## What

`banker-copilot-service` gets its own UAMI, its own Kubernetes service account
and its own federated credential (`infra/cloud/identity-copilot.tf`), with a
grant set chosen to make the epic §2.1 service split true at the platform layer:

| Resource | Grant |
|---|---|
| `copilot-sessions`, `copilot-artifacts`, `copilot-traces` | Cosmos Data **Contributor**, scoped per container |
| `copilot-approvals` | Cosmos Data **Reader** (`…0001`, not `…0002`) |
| `authority-policy`, Accounts, Transactions, Transfers, Users, account-applications | **nothing — not even read** |
| Foundry project | `Azure AI User`, not `Azure AI Project Manager` |
| Redis / `banking-events` | **nothing** |
| Storage, AI Search | **nothing** |
| Key Vault | `Key Vault Secrets User` — see the caveat below |

## Why this and not "same as authority-service"

The invariant is *agents never approve*, and the stated enforcement mechanism is
that the harness registers zero write tools. **That is a property of Python
source, and Python source is one pull request away from being different.** A role
assignment is a property of Entra: changing it produces a Terraform diff that
reads as an infrastructure change rather than a refactor, and it holds even if
the tool manifest is wrong.

The single most load-bearing character in the file is the `1` in
`…sqlRoleDefinitions/00000000-0000-0000-0000-000000000001` on `copilot-approvals`.
The harness must **read** approvals — it renders the card and watches the status
change — and must never **write** one. A harness holding Contributor there could
set `status: signed` on its own proposal. No amount of tool-manifest discipline
upstream would stop that, and no test that reads the manifest would notice.

## The three deliberate omissions, which are the actual design

**No Redis.** `authority-service` owns audit publishing (§5.7); the harness has no
audit responsibility. Redis data access here is write access to `banking-events`,
i.e. the ability to **forge an audit event** — including an `ApprovalSigned` — for
the one component in the system defined by its inability to act. Containing a
component in the data plane and then handing it the audit bus undoes the
containment through the back door: the record of what happened would become
writable by the thing being recorded. If Phase 3 fan-out needs a stream, it gets
its own with its own access policy, never the audit bus.

**No banking Cosmos reads.** The harness reads account and transaction state
through the twelve GET tools of `config/copilot-tools.yaml`, which are HTTP calls
to the owning services carrying the banker's own bearer token — and therefore
subject to those services' authorization checks. A direct Cosmos read "because it
needs the data anyway" would bypass every one of those checks and reduce the tool
manifest to documentation.

**`Azure AI User`, not `Azure AI Project Manager`.** The shared identity holds
Project Manager because `ai-service` and `chatbot-service` *provision* agents. The
harness only *runs* one. Project Manager additionally permits creating and
deleting projects and connections — control-plane capability in a request-path
service.

## The hole, stated plainly

`Key Vault Secrets User` is required: the harness verifies the banker's bearer
token on every request and must read the JWT signing key. Under **#334** that key
is a **symmetric HMAC secret shared by every service**, so the ability to *verify*
a token is indistinguishable from the ability to *mint* one. This grant therefore
also confers "forge a token for any identity, including a supervisor" — and a
forged supervisor token calling `authority-service` directly satisfies an L2
signature slot with no human involved.

Everything else in that file narrows the harness. This one grant is the hole, and
it is **not closable at the platform layer**. It closes when #334 gives
`authority-service` an asymmetric key and a mediator-only audience, so that
holding verification material cannot produce signing material.

I am recording it rather than quietly granting it because a least-privilege
boundary with an undocumented exception is worse than no boundary: it invites the
belief that the boundary holds. Concretely — **we may not describe the Phase 2
harness as "unable to authorise its own actions."** It is unable to do so through
Cosmos, through the tool manifest and through the gateway. It remains able to do
so by minting a token, until #334 lands. #334 is now blocking two separate claims
in this epic, not one.

## Note on #336

Still partial, and now deliberately so. Two services (`authority-service`,
`banker-copilot-service`) have dedicated identities; the other nine still share
`banking-workload-identity` with **account-scoped** Cosmos Data Contributor. The
pattern is established twice over and the remaining work is mechanical, but it
touches every service and belongs in its own change rather than riding along with
an epic phase.

Worth stating the asymmetry: the shared identity's account-wide Contributor means
any of those nine services can already write `copilot-approvals` directly. The
harness is contained; the rest of the mesh is not. That is #336's remaining value
and the reason it should not be treated as closed.
