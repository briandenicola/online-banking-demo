using System.Reflection;
using Banking.Auth;
using FluentAssertions;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Routing;
using UserService.Controllers;
using Xunit;

namespace UserService.Tests;

/// <summary>
/// A banking supervisor may READ the login audit. A banking supervisor may not manage users.
///
/// <para>
/// Epic #332 §5.8.2 keeps <c>admin</c> and <c>supervisor</c> on orthogonal axes so that the person
/// co-signing an L2 approval cannot rewrite the policy governing their own co-signature, or
/// promote themselves. Granting read-only observability must not erode that, and the erosion
/// would not look dramatic in a diff: it is one role string added to one attribute.
/// </para>
///
/// <para>
/// These tests read AUTHORIZATION METADATA off the controller types, not behaviour through the
/// controller. That distinction is load-bearing here. The existing
/// <see cref="AdminSecurityTests"/> notes in its own comments that "in unit tests, authorization
/// attributes are not enforced" — so a test that calls <c>PromoteToAdmin</c> as a supervisor and
/// watches it succeed proves nothing about the gate. Reflection over the attributes is the only
/// thing in this project that actually asserts who may call what.
/// </para>
/// </summary>
[Trait("Category", "Security")]
[Trait("Epic", "332")]
public class SupervisorObservabilityScopeTests
{
    private static readonly string[] WriteVerbs = { "POST", "PUT", "DELETE", "PATCH" };

    private static IEnumerable<MethodInfo> ActionsOf<T>() =>
        typeof(T).GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(m => m.GetCustomAttributes<HttpMethodAttribute>().Any());

    /// <summary>
    /// Every role string that can admit a caller to this action: the controller's gate ANDed with
    /// the action's own. ASP.NET Core ANDs them, so the EFFECTIVE set is the intersection — an
    /// action attribute can only narrow. We return both levels and let each test say which it
    /// means, because conflating them is exactly how someone concludes "it's fine, the method has
    /// an admin attribute" about a class that never had one.
    /// </summary>
    private static string[] RolesOn(MemberInfo member) =>
        member.GetCustomAttributes<AuthorizeAttribute>()
            .SelectMany(a => (a.Roles ?? string.Empty).Split(',', StringSplitOptions.RemoveEmptyEntries))
            .Select(r => r.Trim().ToLowerInvariant())
            .Distinct()
            .ToArray();

    private static bool SupervisorReachable(Type controller, MethodInfo action)
    {
        // AND semantics: a supervisor gets through only if EVERY level that declares roles
        // includes supervisor.
        var levels = new[] { RolesOn(controller), RolesOn(action) }.Where(r => r.Length > 0);
        return levels.All(roles => roles.Contains("supervisor"));
    }

    /// <summary>
    /// THE guard for the demo's story. User management is admin-only, and that includes reading
    /// the user list: the whole tab is admin-only per the approved grant, not merely its writes.
    ///
    /// The bad edit this catches is the obvious one — someone adds <c>supervisor</c> to
    /// <see cref="AdminController"/>'s class attribute so the Login Audit tab "just works" —
    /// which would hand a co-signer <c>promote</c>, <c>reset-password</c> and
    /// <c>DELETE users/{id}</c> in a single character-level change.
    /// </summary>
    [Fact]
    public void No_action_on_AdminController_is_reachable_by_a_supervisor()
    {
        var actions = ActionsOf<AdminController>().ToArray();

        // Anti-vacuous: the controller really does expose actions. A rename or a move would
        // otherwise empty this list and the assertion would pass while defending nothing.
        actions.Should().NotBeEmpty("AdminController must still expose the user-management actions");
        actions.Select(a => a.Name).Should().Contain(new[]
        {
            nameof(AdminController.PromoteToAdmin),
            nameof(AdminController.DeleteUser),
            nameof(AdminController.GetAllUsers),
            nameof(AdminController.ResetPassword)
        }, "these are the actions whose exposure would break separation of duties");

        foreach (var action in actions)
        {
            SupervisorReachable(typeof(AdminController), action).Should().BeFalse(
                $"AdminController.{action.Name} must stay admin-only — a supervisor who could " +
                "reach user management could promote themselves and then hold both signatures " +
                "on their own L2 approval");
        }
    }

    /// <summary>
    /// The read-only controller is genuinely read-only. If a mutating action is ever added here —
    /// the natural mistake, since the class is called "Admin…" and sits beside the real one —
    /// this fails immediately rather than at the next security review.
    /// </summary>
    [Fact]
    public void Every_action_on_AdminObservabilityController_is_a_GET()
    {
        var actions = ActionsOf<AdminObservabilityController>().ToArray();
        actions.Should().NotBeEmpty("the observability controller must expose the login audit read");

        foreach (var action in actions)
        {
            var verbs = action.GetCustomAttributes<HttpMethodAttribute>()
                .SelectMany(a => a.HttpMethods)
                .Select(v => v.ToUpperInvariant())
                .ToArray();

            verbs.Should().NotIntersectWith(WriteVerbs,
                $"AdminObservabilityController.{action.Name} mutates state but sits behind the " +
                "supervisor-readable gate. Read-only means read-only; move it to AdminController.");
        }
    }

    /// <summary>
    /// The grant is live. Without this the two tests above would both pass on a build where the
    /// feature was never implemented — supervisors refused everywhere is trivially "safe" and
    /// completely useless.
    /// </summary>
    [Fact]
    public void A_supervisor_may_read_the_login_audit()
    {
        var action = ActionsOf<AdminObservabilityController>()
            .Single(m => m.Name == nameof(AdminObservabilityController.GetLoginAudits));

        SupervisorReachable(typeof(AdminObservabilityController), action).Should().BeTrue(
            "a supervisor judging an L2 approval needs the login audit as background");

        RolesOn(typeof(AdminObservabilityController)).Should().Contain("admin",
            "admins must not lose access when supervisors gain it");
    }

    /// <summary>
    /// The observability gate is a NAMED symbol, and it names both roles and nothing else.
    ///
    /// This is the anchor that keeps the grant from becoming a hierarchy change by another route:
    /// if someone "simplifies" by adding a role here, every controller carrying the constant is
    /// widened at once, silently. Spelling the expected contents out means that edit has to
    /// come past this test.
    /// </summary>
    [Fact]
    public void The_observability_role_list_names_admin_and_supervisor_and_nothing_else()
    {
        var roles = BankingRoles.ObservabilityRead
            .Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(r => r.Trim().ToLowerInvariant())
            .Distinct()
            .ToArray();

        roles.Should().BeEquivalentTo(new[] { "admin", "supervisor" });

        BankingRoles.Admin
            .Split(',', StringSplitOptions.RemoveEmptyEntries)
            .Select(r => r.Trim().ToLowerInvariant())
            .Distinct()
            .Should().BeEquivalentTo(new[] { "admin" },
                "the admin-only constant must never acquire a second role");
    }
}
