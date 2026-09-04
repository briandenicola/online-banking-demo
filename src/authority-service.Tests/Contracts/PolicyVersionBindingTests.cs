using BankerCopilotTests.Spec;
using FluentAssertions;
using Xunit;

namespace BankerCopilotTests.Contracts;

/// <summary>
/// Epic §5.3.1. "One policyVersion, byte-identical across the approval record, every signature
/// hash input, the trace frame, and the audit events."
///
/// WHY THIS IS THE EASIEST CRITERION TO PASS VACUOUSLY, and it is worth being explicit:
/// the obvious test asserts `approval.PolicyVersion == policyVersion` — comparing a field to the
/// variable it was assigned from, one line earlier, in the same test. It cannot fail. It will sit
/// green forever while the audit emitter recomputes the version from the live policy file and
/// drifts the moment anyone edits it.
///
/// So every assertion here compares values that travelled through DIFFERENT code paths, and the
/// critical ones run AFTER a policy edit — because drift is invisible until the two sources
/// disagree, and they only disagree once the policy has changed.
/// </summary>
public sealed class PolicyVersionBindingTests
{
    [Fact]
    public void The_policy_version_has_the_specified_shape()
    {
        // §6.2.1: "pv1:" + first 16 hex chars of the SHA-256 of the resolved policy.
        var version = PolicyLoader.DerivePolicyVersion(TestData.Baseline());

        version.Should().StartWith("pv1:");
        version.Should().MatchRegex("^pv1:[0-9a-f]{16}$",
            "a stable, greppable shape — an operator reading an audit log must be able to tell " +
            "at a glance whether two events happened under the same policy");
    }

    [Fact]
    public void The_version_is_derived_from_the_RESOLVED_policy_not_the_file_bytes()
    {
        // §6.2.1 point 2, and this is the subtle one. If the version hashed the policy FILE, a
        // threshold overridden by a ConfigMap or an env var would change the effective policy
        // while leaving the version identical — and the re-evaluation gate would see "same
        // version, nothing to do" and honour a signature taken under different rules.
        var baseline = TestData.Baseline();
        var overridden = baseline.WithThreshold("loan_l1_max", "1.00");

        PolicyLoader.DerivePolicyVersion(overridden)
            .Should().NotBe(PolicyLoader.DerivePolicyVersion(baseline),
                "an override that changes behaviour must change the version, or the gate is blind " +
                "to the change that matters most");
    }

    [Fact]
    public void The_version_is_stable_for_an_unchanged_policy()
    {
        // The complement. A version that changes on every load would void every in-flight
        // approval on every pod restart — and the fix someone would reach for is to stop
        // comparing versions at all.
        var first = PolicyLoader.DerivePolicyVersion(TestData.Baseline());

        for (var i = 0; i < 20; i++)
        {
            PolicyLoader.DerivePolicyVersion(TestData.Baseline()).Should().Be(first);
        }
    }

    [Fact]
    public void A_cosmetic_edit_does_not_change_the_version()
    {
        // Reordering keys or reformatting must not void signatures. If it did, every
        // pretty-printer run would be a production incident.
        var a = TestData.Baseline();
        var b = PolicyLoader.Load("baseline-reformatted.json");

        PolicyLoader.DerivePolicyVersion(b).Should().Be(PolicyLoader.DerivePolicyVersion(a),
            "the version binds MEANING, not formatting");
    }

    [Fact]
    public void The_approval_record_the_signatures_and_the_audit_events_all_carry_the_same_version()
    {
        var policy = TestData.Baseline();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var ctx = TestData.TransferReversal(policy);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var signed = store.Get(approval.Id);
        var filled = signed.SignatureSlots.Where(s => s.IsFilled).ToList();

        filled.Should().NotBeEmpty("otherwise the loop below asserts nothing");

        signed.PolicyVersion.Should().Be(version);
        filled.Should().OnlyContain(s => s.BoundPolicyVersion == signed.PolicyVersion,
            "each signature is bound to the version the human saw");

        store.AuditLog.Should().NotBeEmpty();
        store.AuditLog.Should().OnlyContain(e => e.PolicyVersion == signed.PolicyVersion,
            "an audit event under a different version cannot be joined to its approval");
    }

    [Fact]
    public void The_binding_survives_a_policy_edit_which_is_the_only_time_drift_is_visible()
    {
        // THE TEST THAT ACTUALLY CATCHES DRIFT. Sign under policy A, edit the policy to B, then
        // assert every stored artefact still reads A. A component that recomputes from the LIVE
        // policy passes every other test in this file and fails only here.
        var policyA = TestData.Baseline();
        var versionA = PolicyLoader.DerivePolicyVersion(policyA);
        var ctx = TestData.TransferReversal(policyA);
        var (store, approval, _) = TestData.ProposeL1(policyA, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policyA, approval.PayloadHash, "n", TestData.T0);

        var policyB = policyA.WithThreshold("transfer_l2_amount", "1.00");
        var versionB = PolicyLoader.DerivePolicyVersion(policyB);
        versionB.Should().NotBe(versionA, "the fixture must actually change something");

        var afterEdit = store.Get(approval.Id);

        afterEdit.PolicyVersion.Should().Be(versionA,
            "the stored version is a historical fact and must not follow the live policy");
        afterEdit.SignatureSlots.Where(s => s.IsFilled)
            .Should().OnlyContain(s => s.BoundPolicyVersion == versionA);
        store.AuditLog.Should().OnlyContain(e => e.PolicyVersion == versionA);
    }

    [Fact]
    public void Verification_uses_the_stored_version_while_authority_uses_the_live_one()
    {
        // §6.4: "signature verification is archaeology; authority is live." They must not share
        // an input. If the hash were recomputed under the CURRENT version, every policy edit
        // would invalidate every payload hash and the system would refuse everything — and the
        // fix someone would reach for is to drop the version from the hash preimage entirely,
        // which reopens the cross-version replay this prevents.
        var policyA = TestData.Baseline();
        var versionA = PolicyLoader.DerivePolicyVersion(policyA);
        var ctx = TestData.TransferReversal(policyA);
        var (store, approval, _) = TestData.ProposeL1(policyA, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policyA, approval.PayloadHash, "n", TestData.T0);

        // A RELAXING edit: unrelated threshold moved, same rung for this action.
        var policyB = policyA.WithThreshold("loan_l1_max", "9999999.00");
        var versionB = PolicyLoader.DerivePolicyVersion(policyB);

        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), policyB, versionB, ctx, TestData.T0.AddMinutes(1));

        outcome.Kind.Should().Be(GateOutcomeKind.Proceed,
            "a policy edit that does not raise this action's rung must not break its hash");

        outcome.Authorization!.SignedUnderPolicyVersion.Should().Be(versionA);
        outcome.Authorization.EvaluatedUnderPolicyVersion.Should().Be(versionB);
        outcome.Authorization.SignedUnderPolicyVersion.Should()
            .NotBe(outcome.Authorization.EvaluatedUnderPolicyVersion,
                "the two are genuinely different values here — if they were equal the assertion " +
                "above would prove nothing");
    }

    [Fact]
    public void The_execution_record_names_both_versions_so_an_auditor_can_reconstruct_the_decision()
    {
        var policy = TestData.Baseline();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var ctx = TestData.TransferReversal(policy);
        var (store, approval, _) = TestData.ProposeL1(policy, ctx);

        store.Sign(approval.Id, TestData.Principal(TestData.Banker, "banker", 1),
            TestData.Hierarchy(), policy, approval.PayloadHash, "n", TestData.T0);

        var outcome = new ExecutionAuthorization.ReEvaluationGate(new SpecReferenceEvaluator())
            .Authorize(store.Get(approval.Id), policy, version, ctx, TestData.T0.AddMinutes(1));

        var executed = store.Execute(outcome.Authorization!, 200);

        executed.Status.Should().Be(ApprovalStatus.Executed);

        var execEvents = store.AuditLog.Where(e => e.Type.Contains("Executed")).ToList();
        execEvents.Should().NotBeEmpty();
        execEvents.Should().OnlyContain(e => e.PolicyVersion == version);
    }

    [Fact]
    public void The_human_readable_explanation_carries_no_second_copy_of_the_version()
    {
        // §5.3.1: one definition. A version echoed into free-text explanation is a second copy
        // that nothing keeps in sync, and it is exactly the copy an auditor will read.
        var policy = TestData.Baseline();
        var ctx = TestData.LoanDecision(policy);
        var decision = new SpecReferenceEvaluator().Evaluate(ctx, policy);

        decision.RungExplanation.Should().NotBeNullOrWhiteSpace();
        decision.RungExplanation.Should().NotContain("pv1:",
            "the explanation explains the RUNG; the version lives in exactly one field");
    }
}
