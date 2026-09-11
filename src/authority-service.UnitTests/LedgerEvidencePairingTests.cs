using AuthorityService.Models;
using AuthorityService.Policy;
using FluentAssertions;
using Xunit;

namespace AuthorityService.UnitTests;

/// <summary>
/// Ruling §B3.2 — a policy that requires <c>list_account_transactions</c> without
/// <c>get_account</c> must abort startup.
///
/// <para>
/// The residual ambiguity §B2 cannot close: transaction-service DOES NOT OWN ACCOUNTS. Asked
/// about an accountId that does not exist it answers <c>200 []</c>, which is the same answer it
/// gives for an account with a clean history. Nothing downstream can separate those two facts,
/// so the pairing has to be enforced where the demand is declared. Requiring get_account beside
/// it means a nonexistent account 404s, its evidence key is absent, <c>EvidenceComplete</c> fails
/// and the propose is rejected — after which <c>count: 0</c> can only ever mean what it says.
/// </para>
/// </summary>
public class LedgerEvidencePairingTests
{
    [Fact]
    public void A_policy_requiring_the_ledger_without_the_account_refuses_to_start()
    {
        // Mutates the SHIPPED policy, through a harness that throws if the text it is looking for
        // has moved. A mutation that silently matched nothing would load a valid policy, see no
        // exception, and report that the invariant holds when it was never challenged.
        var yaml = TestHarness.MutatedPolicyYaml(
            "requiredEvidence: [get_account, list_account_transactions]",
            "requiredEvidence: [list_account_transactions]");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*list_account_transactions*")
            .WithMessage("*get_account*")
            .WithMessage("*will not start*");
    }

    [Fact]
    public void The_abort_message_says_it_is_about_a_fact_the_transaction_service_cannot_see()
    {
        // The next person to hit this needs to know it is not a preference for thoroughness.
        var yaml = TestHarness.MutatedPolicyYaml(
            "requiredEvidence: [get_account, list_account_transactions]",
            "requiredEvidence: [list_account_transactions]");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().Throw<PolicyValidationException>()
            .WithMessage("*does not own accounts*");
    }

    [Fact]
    public void Requiring_the_account_WITHOUT_the_ledger_is_perfectly_legal()
    {
        // The rule is directional, not a claim that the two keys belong together. get_account
        // answers existence on its own; it is the ledger that cannot stand alone.
        var yaml = TestHarness.MutatedPolicyYaml(
            "requiredEvidence: [get_account, list_account_transactions]",
            "requiredEvidence: [get_account]");

        var act = () => PolicyLoader.FromConfiguration(TestHarness.Configuration()).LoadFromYaml(yaml);

        act.Should().NotThrow();
    }

    [Fact]
    public void Every_shipped_action_that_requires_the_ledger_also_requires_the_account()
    {
        // The positive control on the guard: the SHIPPED policy complies, and it complies
        // non-vacuously. Three actions had to be amended to satisfy this rule — the ledger was
        // being demanded without any way to know the account existed.
        var policy = TestHarness.LoadPolicy();

        var ledgerActions = policy.Document.ActionTypes
            .Where(a => a.Value.RequiredEvidence.Contains("list_account_transactions"))
            .ToList();

        ledgerActions.Should().NotBeEmpty(
            "if no shipped action requires the ledger, this guard is being measured against " +
            "nothing and the other tests here pass by coincidence");

        ledgerActions.Should().AllSatisfy(a =>
            a.Value.RequiredEvidence.Should().Contain(
                "get_account",
                "action '{0}' asks a supervisor to read a transaction count for an account whose " +
                "existence nothing in the evidence set establishes",
                a.Key));
    }
}
