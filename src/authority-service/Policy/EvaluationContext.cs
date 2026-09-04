using AuthorityService.Models;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Policy;

/// <summary>
/// Everything the evaluator is allowed to look at. Assembled BEFORE evaluation — the evaluator
/// itself performs no I/O, which is what makes it a pure function and therefore safe to run a
/// second time at the execution gate (design §3.5).
/// </summary>
public class EvaluationContext
{
    public required string ActionId { get; init; }
    public required JObject Payload { get; init; }
    public required ActorContext Actor { get; init; }
    public JObject Evidence { get; init; } = new();
    public JObject Facts { get; init; } = new();

    /// <summary>
    /// The single document the predicate resolver reads. Built once, deterministically, so the
    /// same inputs always yield the same rung whether evaluated at propose time or execute time.
    /// </summary>
    public JObject BuildDocument()
    {
        var document = (JObject)Facts.DeepClone();

        document["payload"] = Payload.DeepClone();
        document["actor"] = JObject.FromObject(new
        {
            userId = Actor.UserId,
            username = Actor.Username,
            role = Actor.Role,
            effectiveRoles = Actor.EffectiveRoles,
            seniority = Actor.Seniority,
            sessionId = Actor.SessionId,
            signaturesInWindow = Actor.SignaturesInWindow,
            mutatingProposalsInWindow = Actor.MutatingProposalsInWindow
        });

        var context = document["context"] as JObject ?? new JObject();
        context["selfDealing"] = Actor.SelfDealing;
        document["context"] = context;

        return document;
    }
}

public class ActorContext
{
    public required string UserId { get; init; }
    public string? Username { get; init; }
    public string? Role { get; init; }
    public IReadOnlyList<string> EffectiveRoles { get; init; } = [];
    public int Seniority { get; init; }
    public string? SessionId { get; init; }
    public int SignaturesInWindow { get; init; }
    public int MutatingProposalsInWindow { get; init; }
    public bool SelfDealing { get; init; }
}

public enum DecisionOutcome
{
    /// <summary>Admitted: an approval may be created at <see cref="PolicyDecision.RequiredRung"/>.</summary>
    Admitted,

    /// <summary>Refused outright — unknown action, agent may not propose, or the ladder reached L3.</summary>
    NotPermitted,

    /// <summary>Required evidence is missing. The agent must gather more and re-propose.</summary>
    UnderEvidenced
}

public class PolicyDecision
{
    public required string ActionId { get; init; }
    public required DecisionOutcome Outcome { get; init; }
    public required Rung BaseRung { get; init; }
    public required Rung RequiredRung { get; init; }
    public required int RequiredSigners { get; init; }
    public required int MinSeniority { get; init; }
    public required int TtlSeconds { get; init; }
    public IReadOnlyList<FiredEscalator> FiredEscalators { get; init; } = [];
    public IReadOnlyList<SignatureSlot> SignerSlots { get; init; } = [];
    public IReadOnlyList<string> EvidenceGaps { get; init; } = [];
    public string? RejectionReason { get; init; }
    public IReadOnlyDictionary<string, string> ResolvedThresholdSnapshot { get; init; } =
        new Dictionary<string, string>();

    public bool Admissible => Outcome == DecisionOutcome.Admitted;
}
