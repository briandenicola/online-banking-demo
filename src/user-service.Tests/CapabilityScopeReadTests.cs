using System.Reflection;
using Banking.Auth;
using FluentAssertions;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.Routing;
using UserService.Controllers;
using Xunit;
using YamlDotNet.Serialization;

namespace UserService.Tests;

/// <summary>
/// The login audit is gated on the <c>identity.read</c> capability scope, not on the word "admin"
/// in its URL.
///
/// <para>
/// WHY THIS FILE EXISTS. The Banker Copilot's <c>list_login_audits</c> evidence tool targets
/// <c>/api/admin/login-audits</c>, and the harness calls upstream with the REQUESTING BANKER'S OWN
/// token. Gating that read on the platform role made it 403 for every real caller, and the
/// consequence was not local: evidence gathering failed, so the planner never proposed, so no
/// approval was created, so <c>requiredRung</c> was never <c>L2</c>, so the mandatory fan-out
/// never fired and the supervisor model was never called. <c>user.unlock</c> — an L2 action whose
/// required evidence is exactly <c>[get_user, list_login_audits]</c> — could not complete at all.
/// </para>
///
/// <para>
/// <c>config/authority-policy.yaml</c> had already ratified the answer (<c>identity.read: { roles:
/// [banker, supervisor] }</c>) and <c>PolicyLoader.ValidateCapabilityScopes</c> already validated
/// it. It was enforced nowhere. This is the enforcement's test.
/// </para>
///
/// <para>
/// As with <see cref="SupervisorObservabilityScopeTests"/>, these read AUTHORIZATION METADATA off
/// the controller types rather than calling them: <c>AdminSecurityTests</c> notes in its own
/// comments that unit tests do not enforce <c>[Authorize]</c>, so behavioural assertions here
/// would prove nothing.
/// </para>
/// </summary>
[Trait("Category", "Security")]
[Trait("Epic", "332")]
public class CapabilityScopeReadTests
{
    private const string Scope = "identity.read";

    private static readonly string[] WriteVerbs = { "POST", "PUT", "DELETE", "PATCH" };

    private static string PolicyPath()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "config", "authority-policy.yaml");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new FileNotFoundException("Could not locate config/authority-policy.yaml from the test output.");
    }

    private static string[] ScopeRolesFromRatifiedPolicy(string scope)
    {
        var yaml = new DeserializerBuilder().Build()
            .Deserialize<Dictionary<string, object>>(File.ReadAllText(PolicyPath()));

        var scopes = (Dictionary<object, object>)yaml["capabilityScopes"];
        var definition = (Dictionary<object, object>)scopes[scope];
        return ((List<object>)definition["roles"])
            .Select(r => r.ToString()!.Trim().ToLowerInvariant())
            .ToArray();
    }

    private static string[] Split(string roleList) =>
        roleList.Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(r => r.Trim().ToLowerInvariant())
            .Distinct()
            .ToArray();

    private static IEnumerable<MethodInfo> ActionsOf(Type controller) =>
        controller.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(m => m.GetCustomAttributes<HttpMethodAttribute>().Any());

    private static string[] RolesOn(MemberInfo member) =>
        member.GetCustomAttributes<AuthorizeAttribute>()
            .SelectMany(a => Split(a.Roles ?? string.Empty))
            .Distinct()
            .ToArray();

    /// <summary>
    /// AND semantics: a role gets through only if EVERY level that declares roles includes it.
    /// An action attribute can only narrow, never widen.
    /// </summary>
    private static bool ReachableBy(string role, Type controller, MethodInfo action)
    {
        var levels = new[] { RolesOn(controller), RolesOn(action) }.Where(r => r.Length > 0).ToArray();
        return levels.Length > 0 && levels.All(roles => roles.Contains(role));
    }

    private static IEnumerable<(Type Controller, MethodInfo Action)> AllActions() =>
        typeof(AdminController).Assembly.GetTypes()
            .Where(t => t.IsClass && !t.IsAbstract && t.Name.EndsWith("Controller", StringComparison.Ordinal))
            .SelectMany(t => ActionsOf(t).Select(a => (t, a)));

    private static string[] VerbsOf(MethodInfo action) =>
        action.GetCustomAttributes<HttpMethodAttribute>()
            .SelectMany(a => a.HttpMethods)
            .Select(v => v.ToUpperInvariant())
            .Distinct()
            .ToArray();

    /// <summary>
    /// The constant mirrors the ratified document. The service does not load the policy at
    /// runtime — a demo does not need policy distribution — so the mirror needs a test or it will
    /// drift the first time the policy changes, and it will drift in the dangerous direction:
    /// the YAML saying a role was removed while the running service keeps admitting it.
    /// </summary>
    [Fact]
    public void The_identity_read_constant_mirrors_the_ratified_capability_scope()
    {
        var ratified = ScopeRolesFromRatifiedPolicy(Scope);

        // Anti-vacuous: an empty scope in the YAML would let the comparison pass while comparing
        // nothing. (The loader also rejects an empty scope, but this test must not depend on it.)
        ratified.Should().NotBeEmpty($"config/authority-policy.yaml must declare roles for {Scope}");

        var enforced = Split(BankingRoles.IdentityRead).Where(r => r != "admin").ToArray();

        enforced.Should().BeEquivalentTo(ratified,
            $"BankingRoles.IdentityRead must enforce exactly the banking roles that " +
            $"config/authority-policy.yaml ratifies for {Scope}");
    }

    /// <summary>
    /// <c>admin</c> is not a member of the scope; it is a separate platform grant applied
    /// alongside it. The policy file struck <c>admin</c> from every capability scope on purpose —
    /// it "made the platform role a superset of banking authority for READ paths too" — and
    /// <c>ValidateCapabilityScopes</c> rejects any scope naming a seniority-0 role. The natural
    /// bad edit is to collapse the two axes back together, which would look like a harmless fix
    /// for an admin who got a 403.
    /// </summary>
    [Fact]
    public void The_ratified_scope_does_not_name_the_platform_role_but_the_endpoint_still_admits_admins()
    {
        ScopeRolesFromRatifiedPolicy(Scope).Should().NotContain("admin",
            "platform power is not banking seniority — epic #332 §5.8.2");

        Split(BankingRoles.IdentityRead).Should().Contain("admin",
            "admins must still reach the Login Audit tab; their access is a platform grant " +
            "sitting alongside the scope, never membership of it");
    }

    /// <summary>
    /// The end-to-end statement of the fix, and of its limit: a banker reaches the login audit and
    /// NOTHING on <see cref="AdminController"/>.
    ///
    /// This is the guard that keeps "a scoped read grant" from becoming "a role promotion in a new
    /// costume". A banker who could reach <c>PromoteToAdmin</c> could make themselves an admin;
    /// combined with the supervisor grant, the person co-signing an L2 approval would hold both
    /// signatures. That is the one failure a demo audience about separation of duties would catch.
    /// </summary>
    [Fact]
    public void A_banker_reaches_the_login_audit_and_nothing_on_AdminController()
    {
        var loginAudits = ActionsOf(typeof(AdminObservabilityController))
            .Single(m => m.Name == nameof(AdminObservabilityController.GetLoginAudits));

        ReachableBy("banker", typeof(AdminObservabilityController), loginAudits).Should().BeTrue(
            "the copilot's list_login_audits tool calls this with the requesting banker's own " +
            "token; refusing it is what made evidence gathering fail and the L2 fan-out never fire");

        var adminActions = ActionsOf(typeof(AdminController)).ToArray();

        // Anti-vacuous: the controller really does still expose user management. A rename or a
        // move would empty this list and the loop below would defend nothing.
        adminActions.Select(a => a.Name).Should().Contain(new[]
        {
            nameof(AdminController.PromoteToAdmin),
            nameof(AdminController.DeleteUser),
            nameof(AdminController.ResetPassword)
        }, "these are the actions whose exposure would break separation of duties");

        foreach (var action in adminActions)
        {
            ReachableBy("banker", typeof(AdminController), action).Should().BeFalse(
                $"AdminController.{action.Name} must stay admin-only — a banker who could reach " +
                "user management could promote themselves");
        }
    }

    /// <summary>
    /// THE structural guard, and the one that covers code not yet written: across the ENTIRE
    /// user-service controller surface, every action a banker can reach is a GET.
    ///
    /// Enumerated off the assembly rather than listed by hand, so a controller added tomorrow is
    /// in scope without anyone remembering this file. The bad edit it catches is the one that the
    /// per-controller tests cannot: someone widening a class gate to <c>IdentityRead</c> on a
    /// controller that has writes, because "it's just a read grant".
    /// </summary>
    [Fact]
    public void Every_action_a_banker_can_reach_in_user_service_is_a_GET()
    {
        var reachable = AllActions()
            .Where(x => ReachableBy("banker", x.Controller, x.Action))
            .ToArray();

        // Anti-vacuous: the grant really was applied somewhere. An empty list would let the loop
        // below pass on a service that had lost the fix entirely.
        reachable.Should().NotBeEmpty(
            "no action is banker-reachable — the identity.read grant is not applied at all, " +
            "which means the copilot's evidence tool is 403-ing again");

        foreach (var (controller, action) in reachable)
        {
            VerbsOf(action).Should().NotIntersectWith(WriteVerbs,
                $"{controller.Name}.{action.Name} is reachable by a banker and mutates state. " +
                "A capability *.read scope may never gate a state change.");
        }
    }
}
