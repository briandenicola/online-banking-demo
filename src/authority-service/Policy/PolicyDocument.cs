using YamlDotNet.Serialization;

namespace AuthorityService.Policy;

/// <summary>
/// The on-disk policy file (<c>config/authority-policy.yaml</c>), deserialized verbatim.
/// This is the raw AST — nothing here is resolved, validated or usable until
/// <see cref="PolicyLoader"/> has produced a <see cref="ResolvedPolicy"/>.
/// </summary>
public class PolicyDocument
{
    public string ApiVersion { get; set; } = string.Empty;
    public PolicyMetadata Metadata { get; set; } = new();
    public PolicyDefaults Defaults { get; set; } = new();
    public Dictionary<string, ThresholdDefinition> Thresholds { get; set; } = [];
    public Dictionary<string, SignerRoleDefinition> SignerRoles { get; set; } = [];
    public Dictionary<string, RungDefinition> Rungs { get; set; } = [];
    public Dictionary<string, EvidenceDefinition> Evidence { get; set; } = [];
    public List<EscalatorDefinition> Escalators { get; set; } = [];
    public Dictionary<string, ActionDefinition> ActionTypes { get; set; } = [];
    public Dictionary<string, CapabilityScopeDefinition> CapabilityScopes { get; set; } = [];
}

public class PolicyMetadata
{
    public string PolicyId { get; set; } = string.Empty;

    /// <summary>Provenance, not rules — excluded from the version hash (design §6.2.1).</summary>
    public string? EffectiveFrom { get; set; }

    /// <summary>Provenance, not rules — excluded from the version hash.</summary>
    public string? Owner { get; set; }

    public string? Description { get; set; }
}

public class PolicyDefaults
{
    /// <summary>Threshold reference (a name in <c>thresholds:</c>), never a literal.</summary>
    public string ApprovalTtl { get; set; } = string.Empty;

    /// <summary>
    /// RETIRED. Kept only so the loader can REJECT a policy that still declares it. The L2
    /// co-signature bar is now DERIVED from <c>rungs.L2.cosignerRoles</c> via the ratified role
    /// hierarchy. As a threshold it was the role model restated a third time, and — being
    /// env-overridable — it let an operator lower dual control to peer-level by setting a number,
    /// without touching any role file or leaving any trace in the role model.
    /// </summary>
    public string? SupervisorSeniority { get; set; }

    /// <summary><c>deny</c> only. <c>allow</c> is not representable and is rejected at load.</summary>
    public string UnknownAction { get; set; } = "deny";

    /// <summary><c>denied</c> only (invariant I-6). Any other value fails the load.</summary>
    public string TtlExpiryOutcome { get; set; } = "denied";

    /// <summary>Decimal scale used to canonicalize money payload fields (design §6.2 rule 4).</summary>
    public int CurrencyScale { get; set; } = 2;

    public List<string> EvidenceRequired { get; set; } = [];

    public BatchApprovalDefaults BatchApproval { get; set; } = new();

    /// <summary>Threshold reference for the retention TTL written once an approval is terminal.</summary>
    public string RetentionSeconds { get; set; } = string.Empty;

    /// <summary>
    /// Threshold reference for the minimum seniority that satisfies an L2 co-signature.
    /// Named here rather than assumed by the engine, so no threshold NAME is hardcoded in code.
    /// </summary>
}

public class BatchApprovalDefaults
{
    public bool Enabled { get; set; }
    public string MaxItems { get; set; } = string.Empty;   // threshold reference
    public bool SameActionTypeOnly { get; set; } = true;
    public string MaxRung { get; set; } = "L1";            // I-10: never L2
}

public class ThresholdDefinition
{
    /// <summary><c>money</c> | <c>count</c> | <c>ratio</c> | <c>duration_seconds</c>.</summary>
    public string Kind { get; set; } = string.Empty;

    public int? CurrencyScale { get; set; }

    /// <summary>ALWAYS a string, even for counts — avoids YAML type coercion.</summary>
    [YamlMember(Alias = "default")]
    public string Default { get; set; } = string.Empty;

    /// <summary>The env var that overrides <see cref="Default"/>. Resolution order: env → default. No third source.</summary>
    public string Env { get; set; } = string.Empty;

    public string Description { get; set; } = string.Empty;
}

public class SignerRoleDefinition
{
    /// <summary>
    /// The claim spellings that denote THIS role. Every entry must be a case variant of the role's
    /// own name — the policy file may not map one role's claim onto another role, which is how a
    /// customer's `user` claim came to satisfy a banker signature slot.
    /// </summary>
    public List<string> ClaimValues { get; set; } = [];

    /// <summary>
    /// Banking seniority, STAMPED IN from user-service's ratified <c>role-hierarchy.yaml</c> at
    /// load — never read from this file. Declaring <c>seniority:</c> in the policy YAML is a
    /// startup error, because a second copy of the ladder is a second opinion about it, and the
    /// copy that drifts is the copy that decides who may sign.
    ///
    /// <para>It lands on the resolved document, so <c>policyVersion</c> covers it: a change to
    /// the hierarchy is a genuine change of ruleset and must move the version.</para>
    /// </summary>
    [YamlIgnore]
    public int Seniority { get; set; }
}

public class RungDefinition
{
    public int RequiredSigners { get; set; } = 1;

    /// <summary>
    /// RETIRED (Danny, 2026-09-04). Kept only so the loader can REJECT a policy that still
    /// declares it. Leaving it silently ignored would be worse than removing it outright: an
    /// operator would read <c>distinctIdentities: 1</c> and believe they had turned dual control
    /// off, when separation of duties is now carried by <c>signatureSlots[].mustDifferFrom</c>
    /// and cannot be turned off from the policy file at all.
    /// </summary>
    public int? DistinctIdentities { get; set; }
    /// <summary>
    /// Roles that may fill a signature slot at this rung. Every entry must carry banking
    /// seniority >= 1 in the role hierarchy — a platform role has no standing here.
    /// </summary>
    public List<string> SignerRoles { get; set; } = [];

    public List<string> CosignerRoles { get; set; } = [];
    public bool RequiresIndependentSecondOpinion { get; set; }

    /// <summary>
    /// This rung is handled OUTSIDE the ladder — the break-glass console, not this service.
    /// <c>platformRoles</c> names who may act there, and it is deliberately a different concept
    /// from <c>signerRoles</c>: platform authority is not banking seniority, and conflating the
    /// two is what let `admin` outrank a supervisor and co-sign an L2 approval.
    /// </summary>
    public bool OutOfHarness { get; set; }

    public List<string> PlatformRoles { get; set; } = [];

    /// <summary>L3 only: the agent may not even propose. Defaults true for L1/L2.</summary>
    public bool Proposable { get; set; } = true;

    public string? Reason { get; set; }
}

public class EvidenceDefinition
{
    public string Description { get; set; } = string.Empty;
    public string Source { get; set; } = string.Empty;
    public List<string> RequiredFields { get; set; } = [];
}

/// <summary>
/// A structured predicate. Deliberately tiny and total: no loops, no function calls,
/// no user-supplied expressions to parse.
/// </summary>
public class PredicateDefinition
{
    /// <summary>Dotted path, resolved against the evaluation document then against the payload.</summary>
    public string Field { get; set; } = string.Empty;

    /// <summary>gte | gt | lte | lt | eq | ne | in | notIn | intersects | countGte | isTrue | isFalse | exists | notEmpty | empty</summary>
    public string Op { get; set; } = string.Empty;

    /// <summary>
    /// A threshold NAME. Required for every numeric comparison — numeric literals are rejected
    /// at load time, which is the "no magic numbers" guard made structural rather than advisory.
    /// </summary>
    public string? Threshold { get; set; }

    /// <summary>A non-numeric literal (enum-ish string or bool). Never a number.</summary>
    public object? Value { get; set; }

    /// <summary>A non-numeric literal list, for <c>in</c> / <c>notIn</c> / <c>intersects</c>.</summary>
    public List<string>? Values { get; set; }

    /// <summary>Compare the absolute value of the field. Money moves in both directions.</summary>
    public bool Abs { get; set; }
}

/// <summary>
/// A global escalator. The grammar admits <c>raiseTo</c>, <c>raiseBy</c>, <c>minRung</c>,
/// <c>minSigners</c> and <c>minSeniority</c> — and nothing that lowers. There is no
/// <c>lowerTo</c>, <c>setRung</c>, <c>exempt</c>, <c>waive</c> or <c>skipApproval</c>,
/// so a policy author cannot express a downgrade (design §3.4 point 5).
/// </summary>
public class EscalatorDefinition
{
    public string Id { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public PredicateDefinition When { get; set; } = new();
    public string? RaiseTo { get; set; }
    public int? RaiseBy { get; set; }
    public string? MinRung { get; set; }
    public string? MinSigners { get; set; }    // threshold reference
    public string? MinSeniority { get; set; }  // threshold reference
    public string ReasonTemplate { get; set; } = string.Empty;
}

/// <summary>An action-local rule. Same combinator, same monotonicity as an escalator.</summary>
public class ActionRuleDefinition
{
    public string Id { get; set; } = string.Empty;
    public PredicateDefinition When { get; set; } = new();
    public string? RaiseTo { get; set; }
    public int? RaiseBy { get; set; }
    public string? MinSigners { get; set; }    // threshold reference
    public string? MinSeniority { get; set; }  // threshold reference
    public string ReasonTemplate { get; set; } = string.Empty;
}

public class ActionDefinition
{
    public string DisplayName { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string BaseRung { get; set; } = "L1";
    public int BaseSigners { get; set; } = 1;
    public bool AgentMayPropose { get; set; } = true;
    public ActionTargetDefinition? Target { get; set; }

    /// <summary>Ordered list of payload paths included in the signed hash (design §6.1).</summary>
    public List<string> HashFields { get; set; } = [];

    /// <summary>Payload paths canonicalized as fixed-scale decimal strings. Floats are rejected here.</summary>
    public List<string> MoneyFields { get; set; } = [];

    public List<string> RequiredEvidence { get; set; } = [];
    public List<ActionRuleDefinition> Rules { get; set; } = [];

    /// <summary>Threshold reference; falls back to <c>defaults.approvalTtl</c>.</summary>
    public string? ApprovalTtl { get; set; }

    public bool Batchable { get; set; }
    public string? BatchMaxItems { get; set; }  // threshold reference
    public string? Note { get; set; }
}

public class ActionTargetDefinition
{
    /// <summary>Logical service name, resolved via configuration — never a literal URL.</summary>
    public string Service { get; set; } = string.Empty;

    public string Method { get; set; } = "POST";
    public string Path { get; set; } = string.Empty;
}

public class CapabilityScopeDefinition
{
    public List<string> Roles { get; set; } = [];
}
