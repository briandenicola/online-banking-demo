namespace Banking.Auth;

using System;
using System.Security.Claims;

/// <summary>
/// The role strings used in <c>[Authorize(Roles = ...)]</c> gates across the .NET services.
///
/// <para>
/// These are AUTHORIZATION LISTS, not a hierarchy. The banking authority ladder lives in
/// <c>config/role-hierarchy.yaml</c> and <c>RoleHierarchy.cs</c> and is ratified as epic #332
/// §5.8.2: <c>supervisor</c> implies <c>banker</c>; <c>admin</c> has seniority 0 and implies
/// NOTHING, because platform power is not banking seniority. Nothing here changes that, and
/// nothing here may be used to work around it.
/// </para>
///
/// <para>
/// <see cref="ObservabilityRead"/> exists so that granting a supervisor read-only visibility is
/// ONE named symbol rather than a role string retyped across four services. That matters for a
/// reason beyond tidiness: a scattered literal can only be defended in aggregate, whereas a named
/// symbol can be enumerated by a test that asserts exactly which endpoints carry it. See
/// <c>SupervisorObservabilityScopeTests</c> in user-service.Tests and prompt-eval-service.Tests.
/// </para>
///
/// <para>
/// The lower/upper duplication is not decoration: <c>[Authorize(Roles = ...)]</c> matches role
/// claims with ordinal (case-sensitive) comparison, and tokens in this repo have historically
/// carried both casings.
/// </para>
/// </summary>
public static class BankingRoles
{
    /// <summary>Platform administration. Every mutating admin endpoint keeps this and only this.</summary>
    public const string Admin = "admin,Admin";

    /// <summary>
    /// READ-ONLY observability: platform admins plus banking supervisors.
    ///
    /// <para>
    /// A supervisor co-signing an L2 approval needs background detail to judge it. They do NOT
    /// become an admin: L3 actions (<c>authority.policy.edit</c>, <c>user.role.promote</c>,
    /// <c>user.delete</c>) stay <see cref="Admin"/>-only, because a co-signer who could rewrite
    /// the policy governing their own co-signature — or promote themselves — is the exact
    /// separation-of-duties failure this ladder exists to prevent.
    /// </para>
    ///
    /// <para>
    /// **This constant may only appear on an endpoint that does not mutate state.** That is not
    /// a convention to be remembered; it is asserted by the scope tests named above, which
    /// enumerate every action method carrying it and fail on any non-GET verb.
    /// </para>
    /// </summary>
    public const string ObservabilityRead = "admin,Admin,supervisor,Supervisor";

    /// <summary>
    /// READ access to the <c>identity.read</c> capability scope: its ratified banking holders,
    /// plus platform admin.
    ///
    /// <para>
    /// <c>config/authority-policy.yaml</c> declares <c>identity.read: { roles: [banker,
    /// supervisor] }</c>, and <c>PolicyLoader.ValidateCapabilityScopes</c> validates it. Until
    /// now nothing ENFORCED it: the endpoint behind the scope was gated on <c>admin</c> because
    /// it sits under an <c>/api/admin/...</c> path. That produced a live defect — the Banker
    /// Copilot calls upstream with the requesting banker's own token, so <c>list_login_audits</c>
    /// returned 403, evidence gathering failed, and the L2 approval that triggers the supervisor
    /// fan-out was never proposed at all.
    /// </para>
    ///
    /// <para>
    /// This grants nothing new in policy terms; it implements a grant already ratified. It is not
    /// a role promotion: a banker gains one read endpoint, not admin. Every mutating endpoint on
    /// <c>AdminController</c> — promote, delete, reset-password — keeps <see cref="Admin"/>.
    /// </para>
    ///
    /// <para>
    /// <c>admin</c> appears here but NOT in the scope. The policy file struck <c>admin</c> from
    /// every capability scope deliberately ("it made the platform role a superset of banking
    /// authority for READ paths too") and the loader rejects any scope naming a seniority-0 role.
    /// So admin access to this endpoint is a separate platform grant sitting alongside the scope,
    /// never part of it. <c>CapabilityScopeReadTests</c> parses the YAML and fails if the banking
    /// half of this list drifts from the ratified document, or if <c>admin</c> leaks into it.
    /// </para>
    /// </summary>
    public const string IdentityRead = "admin,Admin,banker,Banker,supervisor,Supervisor";

    /// <summary>
    /// READ access to a customer's money: their accounts and the transactions recorded against
    /// them. Held by <c>banker</c> and <c>supervisor</c>, and by nothing else.
    ///
    /// <para>
    /// <c>admin</c> is absent DELIBERATELY and by precedent (§5.8.2: admin implies neither banker
    /// nor supervisor). Reading a customer's balance is BANKING authority; reading an identity
    /// record is PLATFORM authority. That is exactly why this is a new constant rather than a
    /// reuse of <see cref="IdentityRead"/>, which carries <c>Admin</c> for the platform reason.
    /// </para>
    ///
    /// <para>
    /// **The blast radius, stated rather than discovered** (ruling §B1.1): one compromised banker
    /// credential reads every customer's balances and transaction history. There is no
    /// relationship or assignment scoping, no purpose-of-access capture and no customer-visible
    /// disclosure — all three are ticketed, and the demo narration says so out loud instead of
    /// implying they are present.
    /// </para>
    /// </summary>
    public const string CustomerFinancialRead = "banker,Banker,supervisor,Supervisor";

    /// <summary>
    /// WRITE access to a customer's money: today, posting a balance adjustment.
    ///
    /// <para>
    /// Same members as <see cref="CustomerFinancialRead"/>, and separate on purpose. A read
    /// authority and a write authority that happen to coincide are still two different
    /// authorities, and the day they diverge must be a one-line change here rather than an audit
    /// of every call site (ruling §B4.3).
    /// </para>
    ///
    /// <para>
    /// **The honest limitation:** in a real bank this write is gated on the APPROVAL RECORD, not
    /// on the role — a banker's authority to adjust a balance comes from the co-signature, not
    /// from their job title. This harness produces exactly that record and does not yet gate on
    /// it. Ticketed deferred-before-`main`: *state-changing endpoints verify the approval, not
    /// the role.*
    /// </para>
    /// </summary>
    public const string CustomerFinancialWrite = "banker,Banker,supervisor,Supervisor";

    /// <summary>
    /// Does <paramref name="principal"/> hold any role in <paramref name="roleList"/>?
    ///
    /// <para>
    /// The constants above are comma-separated because that is the shape
    /// <c>[Authorize(Roles = ...)]</c> takes. Where a check has to happen INSIDE an action — as
    /// it must whenever the answer is "permitted, but the response body depends on who asked" —
    /// this splits the same one list rather than letting a second copy of the members appear as
    /// literals in a controller. One list, two consumers, no drift.
    /// </para>
    /// </summary>
    public static bool Holds(ClaimsPrincipal? principal, string roleList)
    {
        if (principal is null)
        {
            return false;
        }

        foreach (var role in roleList.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (principal.IsInRole(role))
            {
                return true;
            }
        }

        return false;
    }
}
