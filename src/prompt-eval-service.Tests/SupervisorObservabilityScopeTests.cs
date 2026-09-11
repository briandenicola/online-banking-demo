using System.Reflection;
using Banking.Auth;
using FluentAssertions;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Routing;
using PromptEvalService.Controllers;
using Xunit;

namespace PromptEvalService.Tests;

/// <summary>
/// Supervisors may read evaluation results. They may not run, adjudicate, or author them.
///
/// <para>
/// Unlike user-service — where the read-only endpoint was moved to its own controller so the
/// gate on <c>promote</c>/<c>delete</c> was never touched — these two controllers are mostly
/// reads, so the class gate was widened to <see cref="BankingRoles.ObservabilityRead"/> and every
/// mutating action narrowed back with its own <c>[Authorize(Roles = admin)]</c>. ASP.NET Core ANDs
/// controller and action attributes, so that narrowing is real.
/// </para>
///
/// <para>
/// It is also, by itself, fragile in a specific way worth naming: a NEW mutating action added
/// without an attribute inherits the permissive class gate. Absent-attribute-as-permission is the
/// same shape as absent-field-as-permission, which this epic has already been bitten by twice. The
/// first test below is the mitigation — it enumerates the actions rather than trusting the author
/// of the next one to remember, so a POST added tomorrow fails today's test.
/// </para>
/// </summary>
[Trait("Category", "Security")]
[Trait("Epic", "332")]
public class SupervisorObservabilityScopeTests
{
    private static readonly string[] WriteVerbs = { "POST", "PUT", "DELETE", "PATCH" };

    private static readonly Type[] ObservabilityControllers =
    {
        typeof(EvaluationsController),
        typeof(PromptsController)
    };

    private static IEnumerable<MethodInfo> ActionsOf(Type controller) =>
        controller.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(m => m.GetCustomAttributes<HttpMethodAttribute>().Any());

    private static string[] RolesOn(MemberInfo member) =>
        member.GetCustomAttributes<AuthorizeAttribute>()
            .SelectMany(a => (a.Roles ?? string.Empty).Split(',', StringSplitOptions.RemoveEmptyEntries))
            .Select(r => r.Trim().ToLowerInvariant())
            .Distinct()
            .ToArray();

    /// <summary>Controller and action gates are ANDed, so a supervisor needs BOTH to name them.</summary>
    private static bool SupervisorReachable(Type controller, MethodInfo action)
    {
        var levels = new[] { RolesOn(controller), RolesOn(action) }.Where(r => r.Length > 0);
        return levels.All(roles => roles.Contains("supervisor"));
    }

    private static string[] VerbsOf(MethodInfo action) =>
        action.GetCustomAttributes<HttpMethodAttribute>()
            .SelectMany(a => a.HttpMethods)
            .Select(v => v.ToUpperInvariant())
            .ToArray();

    /// <summary>
    /// THE guard. Anything a supervisor can reach on these controllers is a read.
    ///
    /// Enumerated, not listed by hand, so it covers actions that do not exist yet. The bad edit
    /// it catches: adding a mutating action to a controller whose class gate is now permissive and
    /// forgetting the admin attribute — at which point the action is supervisor-writable and looks
    /// entirely normal in review.
    /// </summary>
    [Fact]
    public void No_mutating_action_is_reachable_by_a_supervisor()
    {
        var checkedAny = false;

        foreach (var controller in ObservabilityControllers)
        {
            var actions = ActionsOf(controller).ToArray();
            actions.Should().NotBeEmpty($"{controller.Name} must still expose actions");

            foreach (var action in actions)
            {
                var verbs = VerbsOf(action);
                if (!verbs.Intersect(WriteVerbs).Any())
                {
                    continue;
                }

                checkedAny = true;
                SupervisorReachable(controller, action).Should().BeFalse(
                    $"{controller.Name}.{action.Name} ({string.Join("/", verbs)}) mutates state. " +
                    "A supervisor's grant is observability: running an evaluation, adjudicating " +
                    "an item, or authoring a prompt template is configuration, and stays admin-only.");
            }
        }

        // Anti-vacuous: there really ARE mutating actions here. Without this the loop above would
        // pass on a refactor that deleted or renamed every write, proving nothing.
        checkedAny.Should().BeTrue("these controllers do have write actions; none were examined");
    }

    /// <summary>
    /// The grant is live: a supervisor really can read runs, a run, a comparison, and the prompt
    /// template list. Without this the test above would pass on a build where nothing was granted.
    /// </summary>
    [Theory]
    [InlineData(typeof(EvaluationsController), nameof(EvaluationsController.ListRuns))]
    [InlineData(typeof(EvaluationsController), nameof(EvaluationsController.GetRun))]
    [InlineData(typeof(EvaluationsController), nameof(EvaluationsController.CompareRuns))]
    [InlineData(typeof(PromptsController), nameof(PromptsController.GetAll))]
    [InlineData(typeof(PromptsController), nameof(PromptsController.GetById))]
    public void A_supervisor_may_perform_each_granted_read(Type controller, string actionName)
    {
        var action = ActionsOf(controller).Single(m => m.Name == actionName);

        VerbsOf(action).Should().BeEquivalentTo(new[] { "GET" },
            "a granted read that is not a GET is a contradiction");
        SupervisorReachable(controller, action).Should().BeTrue(
            $"{controller.Name}.{actionName} is part of the approved read-only grant");
    }

    /// <summary>
    /// Admins keep everything they had. A grant that quietly traded one audience for another
    /// would break the admin console while looking like a security improvement.
    /// </summary>
    [Fact]
    public void An_admin_can_still_reach_every_action_on_both_controllers()
    {
        foreach (var controller in ObservabilityControllers)
        {
            foreach (var action in ActionsOf(controller))
            {
                var levels = new[] { RolesOn(controller), RolesOn(action) }.Where(r => r.Length > 0).ToArray();

                levels.Should().NotBeEmpty(
                    $"{controller.Name}.{action.Name} declares no roles at all — it is open to any " +
                    "authenticated caller");
                levels.Should().OnlyContain(roles => roles.Contains("admin"),
                    $"{controller.Name}.{action.Name} no longer admits an admin");
            }
        }
    }
}
