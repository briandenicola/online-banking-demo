using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Store;

/// <summary>
/// Epic §5.5, §5.1.1, invariant I-6: "Expiry is a denial, not a fall-through." An approval that
/// runs out of clock must land in `denied` with `TTL_EXPIRED` and must never execute.
///
/// The dangerous shape here is a system where expiry is implemented ONLY as a background sweeper.
/// If the sweeper is down, slow, or throttled, a stale approval sits in `pending` looking
/// perfectly signable — and the window between "should have expired" and "was marked expired" is
/// exactly the window an attacker wants. So the read path must expire lazily too, and these tests
/// run the sweeper-off cases deliberately.
/// </summary>
public sealed class TtlExpiryTests
{
    private static (ApprovalStore Store, Approval Approval, Policy Policy, string Version, EvaluationContext Ctx)
        Pending()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.TransferReversal(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);
        return (store, approval, policy, version, ctx);
    }

    [Fact]
    public void The_ttl_comes_from_policy_config_and_not_from_a_literal_in_the_service()
    {
        var policy = TestData.Baseline();

        var action = policy.Actions["transfer.reverse"];
        action.TtlMinutes.Should().NotBeNull(
            "if the action omits a TTL the default applies, but a test that hardcodes 60 would " +
            "keep passing after someone changes the default");

        var (_, approval, _, _, _) = Pending();
        var expected = TestData.T0.AddMinutes(action.TtlMinutes ?? policy.Defaults.TtlMinutes);

        approval.ExpiresAt.Should().Be(expected);
    }

    [Fact]
    public void Expiry_produces_denied_with_TTL_EXPIRED()
    {
        var (store, approval, _, _, _) = Pending();

        var expired = store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddSeconds(1));

        expired.Status.Should().Be(ApprovalStatus.Denied);
        expired.TerminalReason.Should().Be(TerminalReason.TtlExpired);
        TerminalReasonNames.Wire(expired.TerminalReason!.Value).Should().Be("TTL_EXPIRED");
    }

    [Fact]
    public void There_is_no_expired_status_anywhere_in_the_lifecycle()
    {
        // §5.1: five states, and `expired` is not one of them. A sixth state would fork every
        // downstream consumer's switch and reintroduce the fall-through this design removes.
        Enum.GetNames<ApprovalStatus>().Should().BeEquivalentTo(
            ["Proposed", "Pending", "Signed", "Executed", "Denied"]);

        Enum.GetNames<ApprovalStatus>().Should().NotContain(
            n => n.Equals("Expired", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void An_expired_approval_never_executes_even_when_fully_signed()
    {
        // The single most important assertion in this file. A signed approval is one API call
        // from a real money movement; the clock is the only thing standing between them.
        var (store, approval, policy, version, ctx) = Pending();

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Signed);

        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), policy, version, ctx, approval.ExpiresAt.AddTicks(1));

        outcome.Kind.Should().Be(GateOutcomeKind.RefuseTtlExpired);
        outcome.Authorization.Should().BeNull();
    }

    [Fact]
    public void Expiry_is_checked_before_quorum_so_the_refusal_reason_is_honest()
    {
        // Ordering matters for more than tidiness. If quorum were checked first, an expired
        // under-signed approval would be reported as "needs another signature" — and a well-
        // meaning operator would go find one, for an approval that can never execute.
        var (store, approval, policy, version, ctx) = Pending();

        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), policy, version, ctx, approval.ExpiresAt.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.RefuseTtlExpired,
            "not RefuseQuorum — expiry is checked first and independently");
    }

    [Fact]
    public void A_signature_arriving_after_expiry_is_rejected_with_the_sweeper_never_having_run()
    {
        // THE SWEEPER-LAG CASE. No call to Sweep() anywhere in this test, on purpose: the record
        // is still literally `pending` in the store. If acceptance consulted only the stored
        // status, this signature would be accepted and the approval would become executable
        // minutes or hours after it should have died.
        var (store, approval, policy, _, _) = Pending();

        var late = store.Sign(
            approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n",
            approval.ExpiresAt.AddSeconds(1));

        late.Accepted.Should().BeFalse(
            "expiry must be enforced on the read/write path, not only by the sweeper");
        late.RejectionCode.Should().Be("TTL_EXPIRED");
        store.Get(approval.Id).QuorumMet.Should().BeFalse();
    }

    [Fact]
    public void A_signature_arriving_exactly_at_the_expiry_instant_is_rejected()
    {
        // Boundary. `>=` vs `>` here is a one-character difference that decides whether a
        // millisecond-wide window exists. Pin it.
        var (store, approval, policy, _, _) = Pending();

        var atBoundary = store.Sign(
            approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", approval.ExpiresAt);

        atBoundary.Accepted.Should().BeFalse("expiresAt is exclusive; the approval is dead at T");
    }

    [Fact]
    public void A_signature_one_tick_before_expiry_is_still_accepted()
    {
        // Positive control for the boundary above. Without it, an implementation that rejects
        // EVERYTHING would satisfy all the negative tests in this file.
        var (store, approval, policy, _, _) = Pending();

        var justInTime = store.Sign(
            approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n",
            approval.ExpiresAt.AddTicks(-1));

        justInTime.Accepted.Should().BeTrue();
    }

    [Fact]
    public void The_sweeper_is_idempotent_and_does_not_rewrite_an_already_terminal_record()
    {
        // The sweeper runs on a timer, possibly on several replicas. Re-stamping a record would
        // move its terminal timestamp and, worse, could overwrite a HUMAN_DENIED with a
        // TTL_EXPIRED — losing the fact that a person actually looked at it and said no.
        var (store, approval, _, _, _) = Pending();

        store.Deny(approval.Id, TestData.Principal(TestData.Supervisor, "supervisor", 2),
            "Customer confirmed the original transfer was intended after all.",
            DenialReasonValidator.FromConfig(), TestData.T0);

        var afterDeny = store.Get(approval.Id);
        afterDeny.TerminalReason.Should().Be(TerminalReason.HumanDenied);

        store.Sweep(approval.ExpiresAt.AddHours(1));
        store.Sweep(approval.ExpiresAt.AddHours(2));

        var afterSweeps = store.Get(approval.Id);
        afterSweeps.TerminalReason.Should().Be(TerminalReason.HumanDenied,
            "a human's refusal outranks the clock and must not be overwritten by it");
        afterSweeps.TerminalAt.Should().Be(afterDeny.TerminalAt);
    }

    [Fact]
    public void The_sweeper_expires_only_records_that_are_actually_past_their_ttl()
    {
        var policy = TestData.Baseline();
        var store = new ApprovalStore();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var evaluator = new SpecReferenceEvaluator();

        var ctx = TestData.TransferReversal(policy);
        var young = store.Propose("apr_young", ctx, evaluator.Evaluate(ctx, policy), policy, version,
            TestData.T0.AddHours(3));
        var old = store.Propose("apr_old", ctx, evaluator.Evaluate(ctx, policy), policy, version,
            TestData.T0);

        var swept = store.Sweep(old.ExpiresAt.AddMinutes(1));

        swept.Should().Be(1);
        store.Get("apr_old").TerminalReason.Should().Be(TerminalReason.TtlExpired);
        store.Get("apr_young").IsTerminal.Should().BeFalse(
            "an approval proposed later has a later expiry; the sweeper must not take the whole queue");
        young.Id.Should().Be("apr_young");
    }

    [Fact]
    public void An_expired_approval_cannot_be_resurrected_into_pending()
    {
        // Terminal means terminal (§5.1). The only forward path is a NEW approval, which means a
        // new human signature — the whole point.
        var (store, approval, policy, _, _) = Pending();
        store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddSeconds(1));

        // There is deliberately no Reopen/Undeny verb at all — the absence IS the control. What
        // an attacker can actually reach is the signing endpoint, so that is what gets probed.
        typeof(ApprovalStore).GetMethods()
            .Select(m => m.Name)
            .Should().NotContain(n =>
                n.Contains("Reopen", StringComparison.OrdinalIgnoreCase) ||
                n.Contains("Undeny", StringComparison.OrdinalIgnoreCase) ||
                n.Contains("Revive", StringComparison.OrdinalIgnoreCase));

        var late = store.Sign(
            approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0.AddHours(9));

        late.Accepted.Should().BeFalse();
        store.Get(approval.Id).TerminalReason.Should().Be(TerminalReason.TtlExpired);
    }

    [Fact]
    public void TTL_expiry_is_excluded_from_denial_rate_metrics()
    {
        // §5.1.1(c). A TTL expiry says a human never got to it — it is a queue-latency signal,
        // not a judgement. Mixing it into "human denial rate" makes a busy Friday afternoon look
        // like a spike in agent misbehaviour, and the metric stops being read.
        TerminalReason.TtlExpired.CountsTowardDenialRate().Should().BeFalse();
        TerminalReason.HumanDenied.CountsTowardDenialRate().Should().BeTrue();
    }
}
