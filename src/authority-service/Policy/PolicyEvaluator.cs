using System.Globalization;
using System.Text.RegularExpressions;
using AuthorityService.Models;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Policy;

public interface IPolicyEvaluator
{
    PolicyDecision Evaluate(EvaluationContext context, ResolvedPolicy policy);
}

/// <summary>
/// The policy evaluator. A pure function of (context, policy) — no I/O, no clock beyond the TTL
/// arithmetic the caller applies, no ambient state.
///
/// <b>Monotonicity is structural, not a discipline.</b> The only combinator here is <c>max</c>
/// over the total order L1 &lt; L2 &lt; L3 (and <c>max</c> over ℕ for signer counts and
/// seniority). There is no assignment of a lower rung anywhere in this file, and the policy
/// grammar has no verb that could ask for one. Adding a fired escalator can only weakly
/// increase every output.
/// </summary>
public class PolicyEvaluator : IPolicyEvaluator
{
    private static readonly Regex Placeholder = new(@"\{([a-zA-Z0-9_.]+)\}", RegexOptions.Compiled);

    public PolicyDecision Evaluate(EvaluationContext context, ResolvedPolicy policy)
    {
        var action = policy.Action(context.ActionId);

        // ---- 1. Action must be known. Unknown ⇒ fail closed. ---------------------------
        if (action is null)
        {
            return Refuse(context.ActionId, Rung.L3,
                $"Unknown action '{context.ActionId}'. The Copilot only performs explicitly " +
                "allowlisted actions.");
        }

        var baseRung = RungOrder.Parse(action.BaseRung);

        // ---- 2. Hard L3: the agent may not even propose. -------------------------------
        if (!action.AgentMayPropose || baseRung == Rung.L3)
        {
            var reason = policy.Document.Rungs.TryGetValue("L3", out var l3) && !string.IsNullOrWhiteSpace(l3.Reason)
                ? l3.Reason!
                : "Out-of-harness action.";

            return Refuse(context.ActionId, Rung.L3,
                $"'{action.DisplayName}' is outside the Copilot's authority. {reason}");
        }

        var document = context.BuildDocument();

        // ---- 3. Evidence completeness, before any policy math. -------------------------
        var requiredEvidence = policy.Document.Defaults.EvidenceRequired
            .Concat(action.RequiredEvidence)
            .Distinct(StringComparer.Ordinal)
            .ToList();

        var gaps = requiredEvidence
            .Where(key => !EvidenceComplete(context.Evidence, key, policy))
            .ToList();

        if (gaps.Count > 0)
        {
            return new PolicyDecision
            {
                ActionId = context.ActionId,
                Outcome = DecisionOutcome.UnderEvidenced,
                BaseRung = baseRung,
                RequiredRung = baseRung,
                RequiredSigners = action.BaseSigners,
                MinSeniority = 0,
                TtlSeconds = 0,
                EvidenceGaps = gaps,
                RejectionReason =
                    "The evidence required for this action is incomplete: " + string.Join(", ", gaps) + "."
            };
        }

        // ---- 4. Baseline. --------------------------------------------------------------
        var rung = baseRung;
        var signers = action.BaseSigners;
        var seniority = 0;
        var fired = new List<FiredEscalator>();

        // ---- 5. Action-local rules. ALL evaluated; none short-circuits. ----------------
        foreach (var rule in action.Rules)
        {
            if (!PredicateEvaluator.Matches(rule.When, document, policy)) continue;

            var raised = Raised(rung, rule.RaiseTo, rule.RaiseBy, minRung: null);

            rung = RungOrder.Max(rung, raised);
            signers = Math.Max(signers, ResolveCount(rule.MinSigners, policy));
            seniority = Math.Max(seniority, ResolveCount(rule.MinSeniority, policy));

            fired.Add(Describe(rule.Id, "action_rule", raised, rule.When, rule.ReasonTemplate,
                document, policy, action.DisplayName));
        }

        // ---- 6. Global escalators. Same combinator, same monotonicity. -----------------
        foreach (var escalator in policy.Document.Escalators)
        {
            if (!PredicateEvaluator.Matches(escalator.When, document, policy)) continue;

            var raised = Raised(rung, escalator.RaiseTo, escalator.RaiseBy, escalator.MinRung);

            rung = RungOrder.Max(rung, raised);
            signers = Math.Max(signers, ResolveCount(escalator.MinSigners, policy));
            seniority = Math.Max(seniority, ResolveCount(escalator.MinSeniority, policy));

            fired.Add(Describe(escalator.Id, "escalator", raised, escalator.When, escalator.ReasonTemplate,
                document, policy, action.DisplayName));
        }

        // ---- 7. Structural floors that policy config cannot weaken. --------------------
        //         Config can raise these; nothing can push them below the floor, because the
        //         floor is applied with max AFTER all policy input.
        signers = Math.Max(signers, 1);                                   // a human ALWAYS signs

        if (rung == Rung.L2)
        {
            var l2 = policy.Rung(Rung.L2);

            signers = Math.Max(signers, Math.Max(l2.RequiredSigners, 2)); // dual control is definitional

            // DERIVED from the roles L2 says may co-sign, via the ratified hierarchy — not a
            // number. It used to be an env-overridable `supervisor_seniority` threshold, which
            // is the role model restated a third time and, worse, one an operator could set to 1
            // to let a peer banker co-sign without ever touching a role file.
            seniority = Math.Max(seniority, policy.MinimumSeniorityAmong(l2.CosignerRoles));
        }
        else
        {
            signers = Math.Max(signers, policy.Rung(rung).RequiredSigners);
        }

        if (rung == Rung.L3)
        {
            var why = fired.Where(f => f.RaisedTo == Rung.L3).Select(f => f.Reason).ToList();

            return Refuse(context.ActionId, Rung.L3,
                "Escalated out of the Copilot: " +
                (why.Count > 0 ? string.Join("; ", why) : "this action now requires handling outside the Copilot."),
                baseRung, fired);
        }

        // ---- 8. Signer slots, with separation of duties baked in. ----------------------
        var slots = new List<SignatureSlot>
        {
            new() { Ordinal = 0, MinSeniority = Math.Max(1, MinimumBankerSeniority(policy)), MustDifferFrom = [] }
        };

        for (var ordinal = 1; ordinal < signers; ordinal++)
        {
            slots.Add(new SignatureSlot
            {
                Ordinal = ordinal,
                MinSeniority = seniority,

                // The co-signer is never the requester. Nothing in the policy grammar can empty
                // this list — there is no verb for it (design §8.6.1).
                MustDifferFrom = [context.Actor.UserId]
            });
        }

        // ---- 9. Bind the clock. --------------------------------------------------------
        var ttlRef = string.IsNullOrWhiteSpace(action.ApprovalTtl)
            ? policy.Document.Defaults.ApprovalTtl
            : action.ApprovalTtl!;

        return new PolicyDecision
        {
            ActionId = context.ActionId,
            Outcome = DecisionOutcome.Admitted,
            BaseRung = baseRung,
            RequiredRung = rung,
            RequiredSigners = signers,
            MinSeniority = seniority,
            TtlSeconds = policy.Threshold(ttlRef).AsInt(),
            FiredEscalators = fired,
            SignerSlots = slots,
            ResolvedThresholdSnapshot = SnapshotFor(fired, policy)
        };
    }

    /// <summary>
    /// Resolves what a rule/escalator raises the rung TO. Every form is monotone: <c>raiseTo</c>
    /// names a target, <c>raiseBy</c> steps up from the current rung, <c>minRung</c> is a floor.
    /// The result is folded with <c>max</c> by the caller, so even a mis-authored rule cannot lower.
    /// </summary>
    private static Rung Raised(Rung current, string? raiseTo, int? raiseBy, string? minRung)
    {
        var result = current;

        if (raiseTo is not null) result = RungOrder.Max(result, RungOrder.Parse(raiseTo));
        if (raiseBy is not null) result = RungOrder.Max(result, RungOrder.RaiseBy(current, raiseBy.Value));
        if (minRung is not null) result = RungOrder.Max(result, RungOrder.Parse(minRung));

        return result;
    }

    private static int MinimumBankerSeniority(ResolvedPolicy policy) =>
        policy.Document.SignerRoles.Values.Select(r => r.Seniority)
              .Where(s => s >= 1).DefaultIfEmpty(1).Min();

    private static int ResolveCount(string? thresholdRef, ResolvedPolicy policy) =>
        string.IsNullOrWhiteSpace(thresholdRef) ? 0 : policy.Threshold(thresholdRef).AsInt();

    private static bool EvidenceComplete(JObject evidence, string key, ResolvedPolicy policy)
    {
        if (evidence[key] is not JObject supplied) return false;
        if (!policy.Document.Evidence.TryGetValue(key, out var definition)) return false;

        return definition.RequiredFields.All(field =>
            supplied[field] is { } value && value.Type != JTokenType.Null);
    }

    private static FiredEscalator Describe(
        string key,
        string scope,
        Rung raisedTo,
        PredicateDefinition when,
        string template,
        JObject document,
        ResolvedPolicy policy,
        string actionLabel)
    {
        ResolvedThreshold? threshold = string.IsNullOrWhiteSpace(when.Threshold)
            ? null
            : policy.Threshold(when.Threshold!);

        return new FiredEscalator
        {
            Key = key,
            Scope = scope,
            RaisedTo = raisedTo,
            ThresholdName = threshold?.Name,
            ThresholdEnv = threshold?.Env,
            ThresholdValue = threshold?.Value,
            Reason = Render(template, document, threshold, actionLabel)
        };
    }

    /// <summary>
    /// Renders a reason template once, at evaluation time. The result is frozen onto the
    /// approval so a record read back a year later shows the reasons as they were evaluated,
    /// not as re-rendered against today's config.
    /// </summary>
    private static string Render(string template, JObject document, ResolvedThreshold? threshold, string actionLabel)
    {
        return Placeholder.Replace(template, match =>
        {
            var token = match.Groups[1].Value;

            return token switch
            {
                "threshold_value" => threshold?.Value ?? match.Value,
                "threshold_name" => threshold?.Name ?? match.Value,
                "threshold_env" => threshold?.Env ?? match.Value,
                "action_label" => actionLabel,
                _ => Stringify(PredicateEvaluator.Resolve(document, token)) ?? match.Value
            };
        });
    }

    private static string? Stringify(JToken? token) => token switch
    {
        null => null,
        JArray array => string.Join(", ", array.Select(e => e.ToString())),
        _ => token.Type == JTokenType.Null ? null : token.Value<string>()
    };

    private static Dictionary<string, string> SnapshotFor(
        IEnumerable<FiredEscalator> fired, ResolvedPolicy policy)
    {
        var snapshot = new Dictionary<string, string>(StringComparer.Ordinal);

        foreach (var escalator in fired.Where(f => f.ThresholdName is not null))
        {
            snapshot[escalator.ThresholdName!] = policy.Threshold(escalator.ThresholdName!).Value;
        }

        return snapshot;
    }

    private static PolicyDecision Refuse(
        string actionId,
        Rung rung,
        string reason,
        Rung? baseRung = null,
        IReadOnlyList<FiredEscalator>? fired = null) => new()
    {
        ActionId = actionId,
        Outcome = DecisionOutcome.NotPermitted,
        BaseRung = baseRung ?? rung,
        RequiredRung = rung,
        RequiredSigners = 0,
        MinSeniority = 0,
        TtlSeconds = 0,
        FiredEscalators = fired ?? [],
        RejectionReason = reason
    };

    private static string ToInvariant(decimal value) => value.ToString(CultureInfo.InvariantCulture);
}
