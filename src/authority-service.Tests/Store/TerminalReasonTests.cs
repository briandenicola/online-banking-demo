using System.Reflection;
using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Store;

/// <summary>
/// Epic §5.1.1: "`terminalReason` is MANDATORY on every `denied` record. A `denied` without one
/// is a bug, not a default."
///
/// The naive test — write a denial without a reason, assert a 400 — proves only that ONE writer
/// validates. The dangerous path is the tenth writer added six months from now: the sweeper, a
/// migration, a back-fill script, a retry handler. Validation at the API edge does not reach any
/// of them. So the assertions here are mostly about REPRESENTABILITY: can a reasonless denial
/// exist as a value at all?
/// </summary>
public sealed class TerminalReasonTests
{
    [Fact]
    public void A_terminal_transition_cannot_be_constructed_without_a_reason()
    {
        // The reason is a positional constructor parameter with no default, so "denied with no
        // reason" is not a value the type system can express. This is stronger than a guard —
        // a guard can be bypassed by a new code path; a missing constructor cannot.
        var ctors = typeof(TerminalTransition).GetConstructors();

        ctors.Should().NotContain(c => c.GetParameters().Length == 0,
            "a parameterless constructor would let `new TerminalTransition()` produce a " +
            "reasonless denial, and every serializer in .NET would find it");

        ctors.Should().OnlyContain(c =>
            c.GetParameters().Any(p =>
                p.ParameterType == typeof(TerminalReason) && !p.HasDefaultValue),
            "the reason must be required, not defaulted — a default silently invents a judgement");
    }

    [Fact]
    public void Denied_status_and_a_terminal_reason_are_the_same_fact()
    {
        // Status is DERIVED from the presence of the terminal transition rather than assigned
        // alongside it. The two therefore cannot disagree, which removes the entire class of bug
        // where status is set to denied and the reason write fails afterwards.
        typeof(Approval).GetProperty(nameof(Approval.Status))!
            .SetMethod.Should().BeNull();

        var policy = TestData.Baseline();
        var (store, approval, _) = TestData.ProposeL1(policy, TestData.TransferReversal(policy));

        store.All().Should().OnlyContain(a =>
            (a.Status == ApprovalStatus.Denied) == (a.TerminalReason != null),
            "denied ⟺ has a reason, in both directions");

        store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddSeconds(1));

        store.All().Should().OnlyContain(a =>
            (a.Status == ApprovalStatus.Denied) == (a.TerminalReason != null));
    }

    [Fact]
    public void The_terminal_reason_enum_is_closed_at_exactly_four_values()
    {
        // §5.1.1. A fifth value added casually — `CANCELLED`, `SYSTEM_ERROR` — is how an
        // undifferentiated bucket returns. Any addition must break this test and be argued for.
        Enum.GetNames<TerminalReason>().Should().HaveCount(4);

        TerminalReasonNames.All.Should().BeEquivalentTo(
            ["HUMAN_DENIED", "POLICY_RUNG_ESCALATED", "PAYLOAD_SUPERSEDED", "TTL_EXPIRED"]);

        TerminalReasonNames.All.Should().OnlyContain(
            n => n == n.ToUpperInvariant(),
            "SCREAMING_SNAKE on the wire, consistently — §0.1");
    }

    [Fact]
    public void Every_enum_member_has_a_wire_name_and_they_round_trip()
    {
        foreach (var reason in Enum.GetValues<TerminalReason>())
        {
            var wire = TerminalReasonNames.Wire(reason);
            wire.Should().NotBeNullOrWhiteSpace();
            TerminalReasonNames.Parse(wire).Should().Be(reason);
        }
    }

    [Theory]
    [InlineData("SUPERSEDED_BY_REPLAN")]   // the pre-ratification spelling
    [InlineData("POLICY_CHANGE")]
    [InlineData("EXPIRED")]
    [InlineData("ttl_expired")]
    [InlineData("HumanDenied")]
    [InlineData("")]
    [InlineData("CANCELLED")]
    public void An_unrecognised_terminal_reason_fails_closed(string wire)
    {
        // Fail CLOSED. A parser that maps the unknown onto a default would turn a corrupt or
        // attacker-supplied document into a plausible-looking denial — or worse, into whatever
        // the default happened to be.
        var act = () => TerminalReasonNames.Parse(wire);

        act.Should().Throw<UnknownTerminalReasonException>();
    }

    [Fact]
    public void The_reason_carries_no_identifier_because_ids_belong_in_their_own_field()
    {
        // §5.1.1: `supersededByApprovalId` is a SEPARATE field. If the id were embedded in the
        // reason string, the enum would stop being an enum and every consumer would be parsing
        // it — which is how closed vocabularies quietly become free text.
        TerminalReasonNames.All.Should().OnlyContain(n => !n.Contains("apr_"));
        TerminalReasonNames.All.Should().OnlyContain(n => !n.Contains(':'));

        typeof(Approval).GetProperties()
            .Select(p => p.Name)
            .Should().Contain("SupersededByApprovalId");
    }

    [Fact]
    public void A_superseded_approval_records_both_the_reason_and_the_successor_id()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.TransferReversal(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        var newCtx = TestData.TransferReversal(policy, amount: 999m);
        var (superseded, replacement) = store.SupersedeByReplan(
            approval.Id, newCtx, new SpecReferenceEvaluator().Evaluate(newCtx, policy),
            policy, version, "apr_replan_1", TestData.T0.AddMinutes(5));

        superseded.TerminalReason.Should().Be(TerminalReason.PayloadSuperseded);
        superseded.SupersededByApprovalId.Should().Be(replacement.Id);
        replacement.SupersededByApprovalId.Should().BeNull();
        replacement.IsTerminal.Should().BeFalse();
        replacement.QuorumMet.Should().BeFalse(
            "a replan starts from zero signatures — the human agreed to the OLD payload");
    }

    [Fact]
    public void A_voided_approval_records_the_escalation_reason_and_a_replacement()
    {
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max - 10_000m;
        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var tightened = policy.WithThreshold("loan_l1_max", (amount - 1m).ToString("F2"));
        var tv = PolicyLoader.DerivePolicyVersion(tightened);
        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), tightened, tv, ctx, TestData.T0.AddMinutes(1));

        var (voided, _) = store.VoidByPolicyChange(
            approval.Id, outcome, ctx, new SpecReferenceEvaluator().Evaluate(ctx, tightened),
            tightened, tv, "apr_replacement", TestData.T0.AddMinutes(1));

        voided.TerminalReason.Should().Be(TerminalReason.PolicyRungEscalated);
        voided.DiscardedSignatures.Should().NotBeEmpty(
            "the discarded signature must be preserved in full — this is the only event in the " +
            "system where a machine throws away a human's signature (§5.7)");
        voided.DiscardedSignatures[0].SignerId.Should().Be(TestData.Banker);
    }

    // ---- Metric grouping (§5.1.1c) -------------------------------------------------------

    [Fact]
    public void A_burst_of_policy_escalations_does_not_move_the_human_denial_rate()
    {
        // The scenario: someone tightens a threshold at 09:00 and forty in-flight approvals void
        // at once. If those landed in the denial-rate metric, the chart would show a dramatic
        // spike in refusals caused entirely by an administrative edit.
        var terminals = Enumerable.Repeat(TerminalReason.PolicyRungEscalated, 40)
            .Concat([TerminalReason.HumanDenied])
            .ToList();

        terminals.Count(r => r.CountsTowardDenialRate()).Should().Be(1);
    }

    [Fact]
    public void Each_terminal_reason_lands_in_a_distinct_metric_bucket()
    {
        Enum.GetValues<TerminalReason>()
            .Select(r => r.MetricBucket())
            .Should().OnlyHaveUniqueItems(
                "if two reasons shared a bucket, the operator could not tell a policy edit from " +
                "a replan, and the reason field would have bought nothing");
    }

    // ---- Immutability --------------------------------------------------------------------

    [Fact]
    public void A_terminal_approval_admits_no_further_state_change()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.TransferReversal(policy);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Deny(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            "Beneficiary account does not match the customer's stated instruction on the call.",
            DenialReasonValidator.FromConfig(), TestData.T0);

        foreach (var attempt in new Func<SignResult>[]
        {
            () => store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
                TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0),
            () => store.Deny(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
                "A second, entirely different and perfectly valid denial reason goes here.",
                DenialReasonValidator.FromConfig(), TestData.T0)
        })
        {
            attempt().Accepted.Should().BeFalse();
        }

        store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddHours(1));

        store.Get(approval.Id).TerminalReason.Should().Be(TerminalReason.HumanDenied,
            "the first terminal transition wins; nothing overwrites a human's recorded judgement");
    }

    [Fact]
    public void Every_denial_written_by_any_store_verb_carries_a_reason()
    {
        // Exercise every verb that can produce a terminal record, then assert the invariant over
        // the whole store. This is the sweep that catches a NEW verb added without validation —
        // it will show up here as a reasonless denial the moment it is exercised.
        var policy = TestData.Baseline();
        var validator = DenialReasonValidator.FromConfig();
        var evaluator = new SpecReferenceEvaluator();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var store = new ApprovalStore();
        var ctx = TestData.TransferReversal(policy);

        var a1 = store.Propose("apr_1", ctx, evaluator.Evaluate(ctx, policy), policy, version, TestData.T0);
        store.Deny(a1.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            "The customer's identity could not be verified on the recorded call.", validator, TestData.T0);

        var a2 = store.Propose("apr_2", ctx, evaluator.Evaluate(ctx, policy), policy, version, TestData.T0);
        store.ExpireByTtl(a2.Id, a2.ExpiresAt.AddSeconds(1));

        var a3 = store.Propose("apr_3", ctx, evaluator.Evaluate(ctx, policy), policy, version, TestData.T0);
        var newCtx = TestData.TransferReversal(policy, amount: 42m);
        store.SupersedeByReplan(a3.Id, newCtx, evaluator.Evaluate(newCtx, policy),
            policy, version, "apr_3b", TestData.T0.AddMinutes(1));

        var denials = store.All().Where(a => a.Status == ApprovalStatus.Denied).ToList();

        denials.Should().HaveCountGreaterThanOrEqualTo(3);
        denials.Should().OnlyContain(a => a.TerminalReason != null);
        denials.Should().OnlyContain(a => a.TerminalAt != null);
    }
}
