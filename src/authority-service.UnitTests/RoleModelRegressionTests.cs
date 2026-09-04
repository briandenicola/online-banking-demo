using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Services;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// Regression cover for two live privilege escalations found by testing this service's policy
/// file AGAINST user-service's ratified role hierarchy — something neither file's own tests could
/// do, because each was internally coherent.
///
/// <list type="number">
///   <item><b>A customer could sign.</b> <c>banker.claimValues</c> listed <c>user</c>/<c>User</c>.
///   The ratified hierarchy gives <c>user</c> seniority 0 — "Customer. No harness access at all."
///   This file promoted that same claim to a signer role at seniority 1, so a retail customer's
///   token satisfied an L1 signature slot.</item>
///   <item><b>admin was a banking superset.</b> Declared at seniority 3, above supervisor, and
///   listed in <c>L2.cosignerRoles</c> — so one admin identity could fill both L2 slots and dual
///   control evaporated with every test still green. §5.8 puts <c>admin</c> at 0, implying
///   neither banker nor supervisor.</item>
/// </list>
///
/// The durable fix is that seniority now has one definition and the loader refuses to start on
/// disagreement; these tests exist so that a regression is loud rather than silent.
/// </summary>
public class RoleModelRegressionTests
{
    private static RoleHierarchy Ratified() => RoleHierarchy.Discover();

    // ---- Bug 1: the customer claim ---------------------------------------------------------

    [Theory]
    [InlineData("user")]
    [InlineData("User")]
    [InlineData("customer")]
    public void A_customer_token_carries_no_seniority_and_can_satisfy_no_slot(string claim)
    {
        var policy = TestHarness.LoadPolicy();
        var customer = TestHarness.FromClaims("cust-1", policy, claim);

        customer.Seniority.Should().Be(0,
            "the ratified hierarchy describes 'user' as a customer with no harness access; if this " +
            "is ever non-zero, a retail token has been promoted into the signing ladder");

        // Every slot the engine can produce, at every rung, must be out of reach.
        foreach (var rung in new[] { Rung.L1, Rung.L2 })
        {
            var definition = policy.Rung(rung);

            definition.SignerRoles.Concat(definition.CosignerRoles)
                .Select(role => policy.MinimumSeniorityAmong([role]))
                .Should().OnlyContain(bar => bar > 0);

            policy.MinimumSeniorityAmong(definition.SignerRoles).Should().BeGreaterThan(customer.Seniority,
                $"a customer must not clear the bar for a {rung} signature");
        }
    }

    [Fact]
    public async Task A_customer_is_refused_when_signing_a_real_L1_approval()
    {
        var harness = TestHarness.Build();
        var policy = harness.Policies.Current;

        var proposal = await harness.Service.ProposeAsync(TestHarness.FlagReview("100.00"), TestHarness.Banker(), null);
        proposal.RequiredRung.Should().Be(Rung.L1);

        var customer = TestHarness.FromClaims("cust-1", policy, "user");

        var act = () => harness.Service.SignAsync(
            proposal.Id, customer, new Contracts.SignRequest(), "jti-cust");

        (await act.Should().ThrowAsync<AuthorityException>())
            .Which.StatusCode.Should().Be(403);
    }

    [Fact]
    public void The_policy_may_not_map_one_roles_claim_onto_another()
    {
        // The exact shape of bug 1, re-armed. It must now be a startup failure, not a promotion.
        var yaml = TestHarness.MutatedPolicyYaml(
            "    claimValues: [banker, Banker]",
            "    claimValues: [banker, Banker, user, User]");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*claimValues*");
    }

    // ---- Bug 2: admin as a banking superset -------------------------------------------------

    [Fact]
    public void Admin_carries_no_banking_seniority_in_the_ratified_hierarchy()
    {
        var hierarchy = Ratified();

        hierarchy.SeniorityOf("admin").Should().Be(0,
            "§5.8 puts admin outside the banking ladder entirely");

        hierarchy.Expand(["admin"]).Should().NotContain(["banker", "supervisor"],
            "if admin implied supervisor, one admin identity could satisfy BOTH signatures on an " +
            "L2 approval — requester and co-signer — and separation of duties would evaporate");
    }

    [Fact]
    public void Admin_is_not_a_signer_role_at_any_in_harness_rung()
    {
        var policy = TestHarness.LoadPolicy();

        foreach (var (name, rung) in policy.Document.Rungs.Where(r => !r.Value.OutOfHarness))
        {
            rung.SignerRoles.Should().NotContain("admin", $"rung {name} is inside the harness");
            rung.CosignerRoles.Should().NotContain("admin", $"rung {name} is inside the harness");
        }

        policy.Document.CapabilityScopes.Values
            .SelectMany(scope => scope.Roles)
            .Should().NotContain("admin",
                "a role with no standing to sign must not be a superset for reading customer data either");
    }

    [Fact]
    public async Task One_admin_identity_cannot_satisfy_both_slots_of_an_L2_approval()
    {
        var harness = TestHarness.Build();
        var policy = harness.Policies.Current;
        var admin = TestHarness.FromClaims("admin-1", policy, "admin");

        admin.Seniority.Should().Be(0, "admin holds no banking seniority");

        // Route 1: admin proposes, then tries to co-sign its own approval. It cannot even open
        // the first slot — which is the point: the escalation was never about the co-sign check.
        var propose = () => harness.Service.ProposeAsync(TestHarness.FlagReview("300000.00"), admin, null);
        await propose.Should().ThrowAsync<AuthorityException>();

        // Route 2: a banker proposes and signs; admin attempts the SECOND slot.
        var proposal = await harness.Service.ProposeAsync(
            TestHarness.FlagReview("300000.00"), TestHarness.Banker(), null);

        proposal.RequiredRung.Should().Be(Rung.L2, "this amount is over the dual-control line");
        proposal.RequiredSigners.Should().Be(2);

        await harness.Service.SignAsync(proposal.Id, TestHarness.Banker(), new Contracts.SignRequest(), "jti-1");

        var cosign = () => harness.Service.SignAsync(
            proposal.Id, admin, new Contracts.SignRequest(), "jti-2");

        (await cosign.Should().ThrowAsync<AuthorityException>())
            .Which.StatusCode.Should().Be(403);

        var stored = await harness.Service.GetAsync(proposal.Id, TestHarness.Banker());
        stored!.Status.Should().Be(ApprovalStatus.Pending, "the second slot must still be open");
    }

    [Fact]
    public void The_loader_refuses_a_rung_that_admits_a_role_with_no_banking_seniority()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            "    cosignerRoles: [supervisor]",
            "    cosignerRoles: [supervisor, admin]");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*admin*");
    }

    // ---- The durable fix: one definition of seniority ---------------------------------------

    [Fact]
    public void Every_signer_role_agrees_with_the_ratified_hierarchy()
    {
        var policy = TestHarness.LoadPolicy();
        var hierarchy = Ratified();

        foreach (var (name, role) in policy.Document.SignerRoles)
        {
            hierarchy.Has(name).Should().BeTrue($"'{name}' must be a role user-service actually issues");

            role.Seniority.Should().Be(hierarchy.SeniorityOf(name),
                $"'{name}' must be worth exactly what the ratified ladder says it is worth");

            role.ClaimValues.Should().OnlyContain(
                claim => string.Equals(claim, name, StringComparison.OrdinalIgnoreCase),
                $"every claim spelling under '{name}' must denote '{name}' and nothing else");
        }
    }

    [Fact]
    public void The_policy_may_not_declare_seniority_at_all()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            "  banker:\n    claimValues: [banker, Banker]",
            "  banker:\n    claimValues: [banker, Banker]\n    seniority: 9");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*seniority*",
                "a declared seniority is silently ignored by the deserializer, so it must be a " +
                "startup error — otherwise the operator reads a number that is not in force");
    }

    [Fact]
    public void A_signer_role_unknown_to_the_hierarchy_is_a_startup_failure()
    {
        var yaml = TestHarness.MutatedPolicyYaml("  supervisor:\n    claimValues:", "  auditor:\n    claimValues:");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>();
    }

    [Fact]
    public void The_L2_cosigner_bar_is_derived_from_the_hierarchy_not_from_a_tunable_number()
    {
        var policy = TestHarness.LoadPolicy();
        var hierarchy = Ratified();

        var decision = Evaluate(policy, "300000.00");

        decision.RequiredRung.Should().Be(Rung.L2);
        decision.SignerSlots[1].MinSeniority.Should().Be(hierarchy.SeniorityOf("supervisor"),
            "the co-signature bar must move only when the ratified ladder moves");

        policy.Thresholds.Keys.Should().NotContain("supervisor_seniority",
            "an env-overridable seniority let dual control be lowered to peer level without " +
            "touching any role file");
    }

    [Fact]
    public void The_retired_supervisor_seniority_knob_is_rejected_rather_than_ignored()
    {
        var yaml = TestHarness.MutatedPolicyYaml(
            "  retentionSeconds: retention_seconds",
            "  retentionSeconds: retention_seconds\n  supervisorSeniority: approval_ttl_default");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>().WithMessage("*supervisorSeniority*");
    }

    private static PolicyDecision Evaluate(ResolvedPolicy policy, string amount)
    {
        var request = TestHarness.FlagReview(amount);

        return new PolicyEvaluator().Evaluate(new EvaluationContext
        {
            ActionId = request.ActionId,
            Payload = request.Payload,
            Evidence = request.Evidence,
            Facts = new Newtonsoft.Json.Linq.JObject(),
            Actor = TestHarness.Banker()
        }, policy);
    }
}
