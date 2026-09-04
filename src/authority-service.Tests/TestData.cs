using BankerCopilotTests.Spec;

namespace BankerCopilotTests;

/// <summary>
/// Builders. Deliberately contain NO thresholds — every number a test needs is read from the
/// policy fixture via <c>policy.Thresholds[...]</c>, so changing config changes the test's
/// expectation with it rather than leaving a green test asserting a stale number.
/// </summary>
public static class TestData
{
    public const string Banker = "user_banker_1";
    public const string OtherBanker = "user_banker_2";
    public const string Supervisor = "user_supervisor_1";
    public const string Admin = "user_admin_1";

    public static readonly DateTimeOffset T0 =
        new(2026, 9, 4, 12, 0, 0, TimeSpan.Zero);

    public static Policy Baseline() => PolicyLoader.Load("baseline.json");
    public static RoleHierarchy Hierarchy() => RoleHierarchy.Load();

    public static Principal Principal(string userId, string role, int seniority, string jti = "jti_1") =>
        new(userId, role, jti, seniority);

    /// <summary>A transfer reversal under the L2 amount ceiling — the canonical L1 case.</summary>
    public static EvaluationContext TransferReversal(
        Policy policy,
        decimal? amount = null,
        string requesterId = Banker,
        IDictionary<string, object?>? facts = null)
    {
        var ceiling = decimal.Parse(policy.Thresholds["transfer_l2_amount"]);

        return new EvaluationContext
        {
            ActionId = "transfer.reverse",
            RequesterId = requesterId,
            Payload = new Dictionary<string, object?>
            {
                ["transferId"] = "trf_88a2",
                ["amount"] = amount ?? ceiling - 1m,
                ["currency"] = "USD",
                ["reason"] = "wire recall",
                ["transferAgeHours"] = 1
            },
            Facts = facts is null
                ? new Dictionary<string, object?>()
                : new Dictionary<string, object?>(facts),
            EvidenceProvided = policy.Actions["transfer.reverse"].RequiredEvidence
        };
    }

    /// <summary>A loan decision. Amount defaults to just under the L1 ceiling from config.</summary>
    public static EvaluationContext LoanDecision(
        Policy policy,
        decimal? amount = null,
        string verdict = "APPROVE",
        string requesterId = Banker,
        IDictionary<string, object?>? facts = null)
    {
        var l1Max = decimal.Parse(policy.Thresholds["loan_l1_max"]);

        return new EvaluationContext
        {
            ActionId = "loan.decision.record",
            RequesterId = requesterId,
            Payload = new Dictionary<string, object?>
            {
                ["loanApplicationId"] = "loan_4417",
                ["amount"] = amount ?? l1Max - 10000m,
                ["currency"] = "USD",
                ["verdict"] = verdict
            },
            Facts = facts is null
                ? new Dictionary<string, object?>()
                : new Dictionary<string, object?>(facts),
            EvidenceProvided = policy.Actions["loan.decision.record"].RequiredEvidence
        };
    }

    public static (ApprovalStore Store, Approval Approval, string PolicyVersion) ProposeL1(
        Policy policy, EvaluationContext ctx, string id = "apr_test_1")
    {
        var store = new ApprovalStore();
        var version = PolicyLoader.DerivePolicyVersion(policy);
        var decision = new SpecReferenceEvaluator().Evaluate(ctx, policy);
        var approval = store.Propose(id, ctx, decision, policy, version, T0);
        return (store, approval, version);
    }
}
