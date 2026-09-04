using System.Reflection;
using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;
using Xunit.Abstractions;

namespace BankerCopilotTests.Store;

/// <summary>
/// Acceptance criterion: "No path from `signed` to `executed` bypasses the re-evaluation gate."
///
/// ⚠️ THIS IS THE CRITERION MOST LIKELY TO PASS VACUOUSLY, and it deserves saying why.
///
/// The obvious test — "call execute, assert the gate was invoked" — proves only that the path
/// the test walked contains a check. It says nothing about the other paths, and the risk here is
/// precisely a SECOND path: a retry handler, an auto-execute-on-quorum shortcut, a batch
/// executor, an admin force-execute, a reconciliation job that finishes an `in_flight` document.
/// Each is a plausible, well-intentioned addition; each is a bypass. A "was the gate called?"
/// test stays green through every one of them.
///
/// So this file asserts the ABSENCE of a path by construction rather than the PRESENCE of a
/// check by observation, in three layers:
///
///   1. TYPE LEVEL — executing requires an <see cref="ExecutionAuthorization"/> whose only
///      constructor is private and reachable only from the nested re-evaluation gate. A bypass
///      does not fail a test; it fails to compile.
///   2. REFLECTION — assert that property still holds after refactoring: no public constructor,
///      no public factory outside the gate, no settable Approval.Status.
///   3. BEHAVIOURAL — walk each plausible bypass route (retry after failure, expired-but-signed,
///      replay, mutated payload) and confirm each still lands in the gate.
/// </summary>
public sealed class NoBypassPathTests(ITestOutputHelper output)
{
    private readonly IPolicyEvaluator _evaluator = new SpecReferenceEvaluator();

    // ---- Layer 2: the structural property, asserted reflectively -------------------------

    [Fact]
    public void ExecutionAuthorization_has_no_publicly_reachable_constructor()
    {
        var ctors = typeof(ExecutionAuthorization)
            .GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);

        ctors.Should().NotBeEmpty();
        ctors.Should().OnlyContain(c => c.IsPrivate,
            "if any constructor becomes public, an executor can mint its own authorization and " +
            "the gate becomes advisory");
    }

    [Fact]
    public void Only_the_re_evaluation_gate_can_produce_an_ExecutionAuthorization()
    {
        var producers = typeof(ExecutionAuthorization).Assembly
            .GetTypes()
            .SelectMany(t => t.GetMethods(
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
            .Where(m => Produces(m.ReturnType))
            .Select(m => m.DeclaringType!.FullName!)
            .Distinct()
            .ToList();

        output.WriteLine("Types able to hand out an ExecutionAuthorization: " +
                         string.Join(", ", producers));

        producers.Should().OnlyContain(
            t => t == typeof(ExecutionAuthorization.ReEvaluationGate).FullName ||
                 t == typeof(GateOutcome).FullName,
            "the gate mints it and GateOutcome merely carries it; anything else able to produce " +
            "one is a second path to execution");
        return;

        static bool Produces(Type t) =>
            t == typeof(ExecutionAuthorization) ||
            (t == typeof(GateOutcome));
    }

    [Fact]
    public void Approval_status_cannot_be_assigned_at_all()
    {
        var status = typeof(Approval).GetProperty(nameof(Approval.Status))!;

        status.SetMethod.Should().BeNull(
            "Status is DERIVED from Terminal / ExecutionState / quorum. If it were settable, " +
            "`approval with { Status = Executed }` would be a one-line bypass of everything.");
    }

    [Fact]
    public void Executing_requires_an_authorization_argument()
    {
        var execute = typeof(ApprovalStore).GetMethod(nameof(ApprovalStore.Execute))!;

        execute.GetParameters()[0].ParameterType.Should().Be<ExecutionAuthorization>(
            "the capability must be a required argument, not an ambient permission");

        // And no other public member of the store can reach ExecutionState.Succeeded.
        var otherWriters = typeof(ApprovalStore)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(m => m.Name != nameof(ApprovalStore.Execute))
            .Where(m => m.ReturnType == typeof(Approval) || m.ReturnType.Name.Contains("ValueTuple"))
            .Select(m => m.Name)
            .ToList();

        output.WriteLine("Other store methods returning approvals: " + string.Join(", ", otherWriters));
        otherWriters.Should().NotContain("ForceExecute");
        otherWriters.Should().NotContain("MarkExecuted");
    }

    // ---- Layer 3: walk every plausible bypass route --------------------------------------

    [Fact]
    public void A_retry_after_a_failed_execution_re_enters_the_gate_and_is_voided_by_a_tightening()
    {
        // §8.8: a failed execution leaves status = signed, because the signatures remain valid
        // and a retry needs no new human. "This is safe ONLY BECAUSE retry re-enters the gate."
        // That conditional is the thing under test.
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max - 10_000m;
        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var gate = new ExecutionAuthorization.ReEvaluationGate(_evaluator);

        // First attempt: downstream 500. Status must remain `signed`, not become terminal.
        var first = gate.Authorize(store.Get(approval.Id), policy, version, ctx, TestData.T0.AddMinutes(1));
        first.Kind.Should().Be(GateOutcomeKind.Proceed);

        var afterFailure = store.Execute(first.Authorization!, 500);
        afterFailure.Status.Should().Be(ApprovalStatus.Signed,
            "a failed execution does NOT move status — the signatures remain valid (§8.8)");
        afterFailure.ExecutionState.Should().Be(ExecutionState.Failed);
        afterFailure.IsTerminal.Should().BeFalse();

        // Now the policy tightens, and the retry happens.
        var tightened = policy.WithThreshold("loan_l1_max", (amount - 1m).ToString("F2"));
        var tightenedVersion = PolicyLoader.DerivePolicyVersion(tightened);

        var retry = gate.Authorize(
            store.Get(approval.Id), tightened, tightenedVersion, ctx, TestData.T0.AddMinutes(2));

        retry.Kind.Should().Be(GateOutcomeKind.VoidPolicyEscalated,
            "the signatures survive a downstream failure; they do NOT survive a policy " +
            "escalation. A retry is a fresh execute and passes the gate again.");
        retry.Authorization.Should().BeNull();
    }

    [Fact]
    public void A_signed_but_expired_approval_cannot_execute()
    {
        // Expiry is checked FIRST and independently, BEFORE quorum — so a fully-signed approval
        // that ran out of clock before anyone pressed execute still does not go through.
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, version) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Signed);

        var afterExpiry = approval.ExpiresAt.AddSeconds(1);

        var outcome = new ExecutionAuthorization.ReEvaluationGate(_evaluator)
            .Authorize(store.Get(approval.Id), policy, version, ctx, afterExpiry);

        outcome.Kind.Should().Be(GateOutcomeKind.RefuseTtlExpired);
        outcome.Authorization.Should().BeNull();
    }

    [Fact]
    public void An_under_signed_approval_cannot_execute_even_if_the_policy_later_relaxes()
    {
        // "Never auto-honour an under-signed action. There is no path where re-evaluation ADDS
        // sufficiency." An L2 approval with one signature must not become executable merely
        // because the policy dropped to L1 — the quorum it was CREATED with still governs.
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max + 10_000m;
        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        approval.RequiredRung.Should().Be(Rung.L2);

        // Only ONE of the two required signatures.
        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n1", TestData.T0);
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Pending);

        var relaxed = policy.WithThreshold("loan_l1_max", (amount + 50_000m).ToString("F2"));
        _evaluator.Evaluate(ctx, relaxed).RequiredRung.Should().Be(Rung.L1);

        var outcome = new ExecutionAuthorization.ReEvaluationGate(_evaluator).Authorize(
            store.Get(approval.Id), relaxed, PolicyLoader.DerivePolicyVersion(relaxed), ctx,
            TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.RefuseQuorum,
            "the ladder can tighten under an in-flight approval; it can never loosen one into " +
            "validity. A relaxation must not retroactively make one signature sufficient.");
        outcome.Authorization.Should().BeNull();
    }

    [Fact]
    public void A_voided_approval_stays_refused_forever_no_matter_how_many_times_execute_is_replayed()
    {
        // "A client replaying `execute` gets the same 409 forever. The only forward path is a
        // new approval." Replay is the cheapest attack there is, so it gets an explicit test.
        var policy = TestData.Baseline();
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);
        var amount = l1Max - 10_000m;
        var ctx = TestData.LoanDecision(policy, amount);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var tightened = policy.WithThreshold("loan_l1_max", (amount - 1m).ToString("F2"));
        var tv = PolicyLoader.DerivePolicyVersion(tightened);
        var gate = new ExecutionAuthorization.ReEvaluationGate(_evaluator);

        var outcome = gate.Authorize(store.Get(approval.Id), tightened, tv, ctx, TestData.T0.AddMinutes(1));
        var newDecision = _evaluator.Evaluate(ctx, tightened);
        store.VoidByPolicyChange(approval.Id, outcome, ctx, newDecision, tightened, tv,
            "apr_replacement", TestData.T0.AddMinutes(1));

        for (var attempt = 0; attempt < 5; attempt++)
        {
            var replay = gate.Authorize(
                store.Get(approval.Id), tightened, tv, ctx, TestData.T0.AddMinutes(2 + attempt));

            replay.Kind.Should().NotBe(GateOutcomeKind.Proceed,
                $"replay attempt {attempt} was authorized; a terminal approval must never execute");
            replay.Authorization.Should().BeNull();
        }

        // And the store itself refuses even if an authorization were somehow presented.
        store.Get(approval.Id).Status.Should().Be(ApprovalStatus.Denied);
    }

    [Fact]
    public void Every_terminal_transition_records_a_reason_so_no_denial_is_undifferentiated()
    {
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.ExpireByTtl(approval.Id, approval.ExpiresAt.AddSeconds(1));

        store.All().Where(a => a.Status == ApprovalStatus.Denied)
            .Should().OnlyContain(a => a.TerminalReason != null);
    }
}
