using System.Globalization;
using System.Text.Json;

namespace BankerCopilotTests.Spec;

/// <summary>Policy-engine §3.1 EvaluationContext, flattened to a dotted-path fact bag.</summary>
public sealed class EvaluationContext
{
    public required string ActionId { get; init; }
    public required IReadOnlyDictionary<string, object?> Payload { get; init; }

    /// <summary>
    /// Non-payload facts consulted by escalators — <c>context.selfDealing</c>,
    /// <c>agent.confidence</c>, <c>customer.riskTier</c>, <c>session.anomalyScore</c>, etc.
    /// </summary>
    public IReadOnlyDictionary<string, object?> Facts { get; init; } =
        new Dictionary<string, object?>();

    public required string RequesterId { get; init; }
    public IReadOnlyList<string> EvidenceProvided { get; init; } = [];

    public bool TryGetFact(string path, out object? value)
    {
        if (Facts.TryGetValue(path, out value)) return true;
        if (Payload.TryGetValue(path, out value)) return true;

        // dotted paths against the payload, e.g. "transfer.amount"
        object? current = Payload;
        foreach (var segment in path.Split('.'))
        {
            if (current is IReadOnlyDictionary<string, object?> d && d.TryGetValue(segment, out current))
                continue;
            value = null;
            return false;
        }

        value = current;
        return true;
    }
}

public sealed record SignerRequirement(int Ordinal, int MinSeniority, IReadOnlyList<string> MustDifferFrom);

public sealed record FiredEscalator(
    string Key,
    string Reason,
    Rung RaisedTo,
    string? ThresholdName,
    string? ThresholdValue);

public sealed record PolicyDecision
{
    public required string ActionId { get; init; }
    public required bool Admissible { get; init; }
    public required Rung BaseRung { get; init; }
    public required Rung RequiredRung { get; init; }
    public required int RequiredSigners { get; init; }
    public required int DistinctIdentitiesRequired { get; init; }
    public required IReadOnlyList<SignerRequirement> SignerRequirements { get; init; }
    public required IReadOnlyList<FiredEscalator> FiredEscalators { get; init; }
    public IReadOnlyList<string> EvidenceGaps { get; init; } = [];
    public string? InadmissibleReason { get; init; }

    /// <summary>
    /// Epic §5.3.1: the human-readable "why this rung". Deliberately DERIVED rather than stored,
    /// so it cannot drift from the decision it explains, and deliberately free of any second copy
    /// of the policyVersion — one definition means one field.
    /// </summary>
    public string RungExplanation =>
        FiredEscalators.Count == 0
            ? $"{ActionId} sits at its base rung {BaseRung} — no escalator applied."
            : $"{ActionId} was raised from {BaseRung} to {RequiredRung} by: " +
              string.Join("; ", FiredEscalators.Select(e => e.Key));
}

public interface IPolicyEvaluator
{
    PolicyDecision Evaluate(EvaluationContext ctx, Policy policy);
}

/// <summary>
/// A faithful transcription of the ratified evaluation algorithm (epic §4.3, policy-engine §3.2).
///
/// THIS IS AN ORACLE, NOT PRODUCTION CODE. It proves the SPECIFIED algorithm has the properties
/// the acceptance criteria claim. When authority-service ships, the same test bodies run against
/// Turk's implementation through <see cref="IPolicyEvaluator"/>, and any divergence between the
/// two is a differential-test failure. Until then, a green monotonicity test means "the spec is
/// monotonic", NOT "the engine is monotonic" — see the Phase 1 test plan, §False passes.
/// </summary>
public sealed class SpecReferenceEvaluator : IPolicyEvaluator
{
    public PolicyDecision Evaluate(EvaluationContext ctx, Policy policy)
    {
        // ---- 1. Unknown action ⇒ fail closed. ---------------------------------------------
        if (!policy.Actions.TryGetValue(ctx.ActionId, out var action))
        {
            return Inadmissible(ctx.ActionId, Rung.L3,
                $"Unknown action '{ctx.ActionId}'. The harness only performs allowlisted actions.");
        }

        var baseRung = RungOrder.Parse(action.BaseRung);

        // ---- 2. Hard L3: the agent may not even propose. -----------------------------------
        if (!action.AgentMayPropose || baseRung == Rung.L3)
        {
            return Inadmissible(ctx.ActionId, Rung.L3,
                $"'{action.DisplayName}' is outside the Copilot's authority (L3).");
        }

        // ---- 3. Evidence completeness gate, before any policy math. ------------------------
        var gaps = action.RequiredEvidence.Where(e => !ctx.EvidenceProvided.Contains(e)).ToList();
        if (gaps.Count > 0)
        {
            return new PolicyDecision
            {
                ActionId = ctx.ActionId,
                Admissible = false,
                BaseRung = baseRung,
                RequiredRung = baseRung,
                RequiredSigners = policy.RungSpecFor(baseRung).RequiredSigners,
                DistinctIdentitiesRequired = policy.RungSpecFor(baseRung).DistinctIdentities,
                SignerRequirements = [],
                FiredEscalators = [],
                EvidenceGaps = gaps,
                InadmissibleReason = "Under-evidenced; the agent must gather more and re-propose."
            };
        }

        // ---- 4. Baseline. -----------------------------------------------------------------
        var rung = baseRung;
        var signers = policy.RungSpecFor(baseRung).RequiredSigners;
        var seniority = policy.RungSpecFor(baseRung).MinSeniority;
        var fired = new List<FiredEscalator>();

        // ---- 5 & 6. Action-local rules THEN global escalators. Same combinator, no
        //             short-circuit, order irrelevant to the result. -------------------------
        foreach (var rule in action.Thresholds.Concat(policy.Escalators))
        {
            if (!Matches(rule.When, ctx, policy)) continue;

            var contributed = ContributedRung(rule, rung);
            rung = RungOrder.Max(rung, contributed);
            signers = Math.Max(signers, rule.MinSigners ?? 0);
            seniority = Math.Max(seniority, rule.MinSeniority ?? 0);

            fired.Add(new FiredEscalator(
                rule.Key,
                RenderReason(rule, ctx, policy),
                contributed,
                rule.When.ValueRef,
                rule.When.ValueRef is { } vr && policy.Thresholds.TryGetValue(vr, out var tv) ? tv : null));
        }

        // ---- 7. Structural floors that policy config CANNOT weaken. -----------------------
        var rungSpec = policy.RungSpecFor(rung);
        signers = Math.Max(signers, 1);                  // a human ALWAYS signs (I-1)
        signers = Math.Max(signers, rungSpec.RequiredSigners);
        var distinct = Math.Max(1, rungSpec.DistinctIdentities);

        if (rung == Rung.L2)
        {
            signers = Math.Max(signers, 2);              // dual control is definitional
            distinct = Math.Max(distinct, 2);
            seniority = Math.Max(seniority, rungSpec.MinSeniority);
        }

        if (rung == Rung.L3)
        {
            return Inadmissible(ctx.ActionId, Rung.L3,
                "Escalated out of the harness: " +
                string.Join("; ", fired.Where(f => f.RaisedTo == Rung.L3).Select(f => f.Reason)),
                baseRung, fired);
        }

        // ---- 8. Signer slots with separation of duties. ------------------------------------
        var reqs = new List<SignerRequirement>
        {
            new(0, policy.RungSpecFor(Rung.L1).MinSeniority, [])
        };
        for (var i = 1; i < signers; i++)
        {
            // The co-signer is NEVER the requester. There is no config value and no policy rule
            // that can empty this list — §8.6.1 / Q4.
            reqs.Add(new SignerRequirement(i, seniority, [ctx.RequesterId]));
        }

        return new PolicyDecision
        {
            ActionId = ctx.ActionId,
            Admissible = true,
            BaseRung = baseRung,
            RequiredRung = rung,
            RequiredSigners = signers,
            DistinctIdentitiesRequired = distinct,
            SignerRequirements = reqs,
            FiredEscalators = fired
        };
    }

    /// <summary>
    /// Both normative spellings, both monotone. <c>raiseTo</c> contributes its literal rung;
    /// <c>raiseBy</c> contributes current+N (N &gt;= 0, enforced at load). <c>minRung</c> is a
    /// floor. Every one of these can only be an input to <c>max</c> — none can replace the rung.
    /// </summary>
    private static Rung ContributedRung(Rule rule, Rung current)
    {
        var contributed = current;

        if (rule.RaiseTo is { } raiseTo)
            contributed = RungOrder.Max(contributed, RungOrder.Parse(raiseTo));

        if (rule.RaiseBy is { } by)
            contributed = RungOrder.Max(contributed, RungOrder.RaiseBy(current, by));

        if (rule.MinRung is { } min)
            contributed = RungOrder.Max(contributed, RungOrder.Parse(min));

        return contributed;
    }

    private static PolicyDecision Inadmissible(
        string actionId, Rung rung, string reason,
        Rung? baseRung = null, IReadOnlyList<FiredEscalator>? fired = null) =>
        new()
        {
            ActionId = actionId,
            Admissible = false,
            BaseRung = baseRung ?? rung,
            RequiredRung = rung,
            RequiredSigners = 0,
            DistinctIdentitiesRequired = 0,
            SignerRequirements = [],
            FiredEscalators = fired ?? [],
            InadmissibleReason = reason
        };

    private static string RenderReason(Rule rule, EvaluationContext ctx, Policy policy)
    {
        var threshold = rule.When.ValueRef is { } vr && policy.Thresholds.TryGetValue(vr, out var v)
            ? v : rule.When.Value?.ToString() ?? "";
        return string.IsNullOrEmpty(rule.Description)
            ? $"{rule.Key}: {rule.When.Field} {rule.When.Op} {threshold}"
            : $"{rule.Description} ({rule.When.Field} {rule.When.Op} {threshold})";
    }

    // ---- Predicate evaluation ---------------------------------------------------------------

    private static bool Matches(Predicate p, EvaluationContext ctx, Policy policy)
    {
        if (!ctx.TryGetFact(p.Field, out var actual) || actual is null) return false;

        var expected = ResolveExpected(p, policy);

        return p.Op switch
        {
            "eq" => ScalarEquals(actual, expected),
            "neq" => !ScalarEquals(actual, expected),
            "gte" => CompareNumeric(actual, expected) >= 0,
            "gt" => CompareNumeric(actual, expected) > 0,
            "lte" => CompareNumeric(actual, expected) <= 0,
            "lt" => CompareNumeric(actual, expected) < 0,
            "in" => AsList(expected).Any(e => ScalarEquals(actual, e)),
            "intersects" => AsList(actual).Any(a => AsList(expected).Any(e => ScalarEquals(a, e))),
            "countGte" => AsList(actual).Count() >= Convert.ToInt64(ToDecimal(expected)),
            _ => throw new InvalidOperationException($"Unknown predicate op '{p.Op}'.")
        };
    }

    private static object? ResolveExpected(Predicate p, Policy policy)
    {
        if (p.ValueRef is { } vr)
        {
            if (!policy.Thresholds.TryGetValue(vr, out var raw))
                throw new InvalidOperationException(
                    $"Threshold '{vr}' is referenced but not defined. Every number lives in " +
                    "policy.thresholds — see policy-engine §2.2.");
            return raw;
        }

        return p.Value is { } je ? FromJson(je) : null;
    }

    private static object? FromJson(JsonElement e) => e.ValueKind switch
    {
        JsonValueKind.String => e.GetString(),
        JsonValueKind.Number => e.GetDecimal(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Array => e.EnumerateArray().Select(FromJson).ToList(),
        _ => null
    };

    private static IEnumerable<object?> AsList(object? v) => v switch
    {
        null => [],
        string s => [s],
        System.Collections.IEnumerable seq => seq.Cast<object?>(),
        _ => [v]
    };

    private static bool ScalarEquals(object? a, object? b)
    {
        if (a is null || b is null) return a is null && b is null;
        if (a is bool || b is bool) return Convert.ToBoolean(a) == Convert.ToBoolean(b);
        if (IsNumeric(a) && IsNumeric(b)) return ToDecimal(a) == ToDecimal(b);
        return string.Equals(a.ToString(), b.ToString(), StringComparison.Ordinal);
    }

    private static int CompareNumeric(object? a, object? b) => ToDecimal(a).CompareTo(ToDecimal(b));

    private static bool IsNumeric(object v) =>
        v is int or long or decimal or double or float ||
        (v is string s && decimal.TryParse(s, NumberStyles.Number, CultureInfo.InvariantCulture, out _));

    private static decimal ToDecimal(object? v) => v switch
    {
        null => 0m,
        decimal d => d,
        string s => decimal.Parse(s, NumberStyles.Number, CultureInfo.InvariantCulture),
        _ => Convert.ToDecimal(v, CultureInfo.InvariantCulture)
    };
}
