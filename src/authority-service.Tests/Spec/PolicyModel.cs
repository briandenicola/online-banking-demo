using System.Text.Json;
using System.Text.Json.Serialization;

namespace BankerCopilotTests.Spec;

/// <summary>
/// Spec-shaped policy model. Deliberately supports BOTH normative spellings found in the two
/// ratified documents:
///   * epic §4.2       — <c>raiseBy</c> (int) + <c>minRung</c>
///   * policy-engine §3.2 — <c>raiseTo</c> (rung) + <c>minSigners</c> / <c>minSeniority</c>
/// The drift between those two is reported as finding F-1 in the Phase 1 test plan. Supporting
/// both here means the monotonicity property is proven for whichever one Turk lands on.
/// </summary>
public sealed record Policy
{
    [JsonPropertyName("policyId")] public string PolicyId { get; init; } = "";
    [JsonPropertyName("defaults")] public PolicyDefaults Defaults { get; init; } = new();
    [JsonPropertyName("rungs")] public Dictionary<string, RungSpec> Rungs { get; init; } = new();
    [JsonPropertyName("thresholds")] public Dictionary<string, string> Thresholds { get; init; } = new();
    [JsonPropertyName("actions")] public Dictionary<string, ActionSpec> Actions { get; init; } = new();
    [JsonPropertyName("escalators")] public List<Rule> Escalators { get; init; } = [];

    public RungSpec RungSpecFor(Rung r) => Rungs[r.ToString()];
}

public sealed record PolicyDefaults
{
    [JsonPropertyName("ttlMinutes")] public int TtlMinutes { get; init; } = 30;
    [JsonPropertyName("ttlExpiryOutcome")] public string TtlExpiryOutcome { get; init; } = "denied";
}

public sealed record RungSpec
{
    [JsonPropertyName("requiredSigners")] public int RequiredSigners { get; init; } = 1;
    [JsonPropertyName("distinctIdentities")] public int DistinctIdentities { get; init; } = 1;
    [JsonPropertyName("signerRoles")] public List<string> SignerRoles { get; init; } = [];
    [JsonPropertyName("cosignerRoles")] public List<string> CosignerRoles { get; init; } = [];
    [JsonPropertyName("proposable")] public bool Proposable { get; init; } = true;
    [JsonPropertyName("minSeniority")] public int MinSeniority { get; init; } = 1;
}

public sealed record ActionSpec
{
    [JsonPropertyName("displayName")] public string DisplayName { get; init; } = "";
    [JsonPropertyName("baseRung")] public string BaseRung { get; init; } = "L1";
    [JsonPropertyName("ttlMinutes")] public int? TtlMinutes { get; init; }
    [JsonPropertyName("agentMayPropose")] public bool AgentMayPropose { get; init; } = true;
    [JsonPropertyName("hashFields")] public List<string> HashFields { get; init; } = [];
    [JsonPropertyName("moneyFields")] public List<string> MoneyFields { get; init; } = [];
    [JsonPropertyName("currencyScale")] public int CurrencyScale { get; init; } = 2;
    [JsonPropertyName("thresholds")] public List<Rule> Thresholds { get; init; } = [];
    [JsonPropertyName("requiredEvidence")] public List<string> RequiredEvidence { get; init; } = [];
}

/// <summary>
/// One rule or escalator. The grammar admits <c>raiseTo</c>, <c>raiseBy</c>, <c>minRung</c>,
/// <c>minSigners</c>, <c>minSeniority</c> — and deliberately NOTHING that lowers. See
/// policy-engine §3.4 point 5: "the dangerous direction is unrepresentable, not merely disallowed."
/// </summary>
public sealed record Rule
{
    [JsonPropertyName("key")] public string Key { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("when")] public Predicate When { get; init; } = new();

    [JsonPropertyName("raiseTo")] public string? RaiseTo { get; init; }
    [JsonPropertyName("raiseBy")] public int? RaiseBy { get; init; }
    [JsonPropertyName("minRung")] public string? MinRung { get; init; }
    [JsonPropertyName("minSigners")] public int? MinSigners { get; init; }
    [JsonPropertyName("minSeniority")] public int? MinSeniority { get; init; }
}

public sealed record Predicate
{
    [JsonPropertyName("field")] public string Field { get; init; } = "";
    [JsonPropertyName("op")] public string Op { get; init; } = "eq";

    /// <summary>Literal comparison value. Mutually exclusive with <see cref="ValueRef"/>.</summary>
    [JsonPropertyName("value")] public JsonElement? Value { get; init; }

    /// <summary>
    /// Name of a threshold in <c>policy.thresholds</c>. This is the "no magic numbers"
    /// indirection of policy-engine §2.2 — tests read the number from config, exactly as
    /// production does, so changing config changes the test's expectation too.
    /// </summary>
    [JsonPropertyName("valueRef")] public string? ValueRef { get; init; }
}

public static class PolicyLoader
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    public static string PolicyDirectory =>
        Path.Combine(AppContext.BaseDirectory, "TestPolicies");

    public static Policy Load(string fileName)
    {
        var path = Path.Combine(PolicyDirectory, fileName);
        if (!File.Exists(path))
            throw new FileNotFoundException(
                $"Test policy '{fileName}' not found at {path}. Tests must read thresholds from " +
                "config, never from literals — a missing policy file is a hard failure, not a skip.",
                path);

        var policy = JsonSerializer.Deserialize<Policy>(File.ReadAllText(path), Options)
                     ?? throw new InvalidOperationException($"Policy '{fileName}' deserialized to null.");

        Validate(policy);
        return policy;
    }

    public static IEnumerable<string> AllPolicyFiles() =>
        Directory.EnumerateFiles(PolicyDirectory, "*.json").Select(Path.GetFileName)!;

    /// <summary>
    /// Load-time grammar validation. This is the executable form of policy-engine §3.4 point 5.
    /// A policy that tries to express a downgrade must fail to load, not merely fail to apply.
    /// </summary>
    private static void Validate(Policy policy)
    {
        foreach (var rule in policy.Actions.Values.SelectMany(a => a.Thresholds).Concat(policy.Escalators))
        {
            if (rule.RaiseBy is < 0)
                throw new InvalidOperationException(
                    $"Rule '{rule.Key}' has a negative raiseBy. Lowering is unrepresentable (I-4).");
            if (rule.MinSigners is < 0)
                throw new InvalidOperationException(
                    $"Rule '{rule.Key}' has a negative minSigners. Lowering is unrepresentable (I-4).");
            if (rule.MinSeniority is < 0)
                throw new InvalidOperationException(
                    $"Rule '{rule.Key}' has a negative minSeniority. Lowering is unrepresentable (I-4).");
        }
    }

    /// <summary>
    /// Derive <c>policyVersion</c> per policy-engine §6.2.1: a content hash of the RESOLVED
    /// policy, so an env/threshold override that leaves the file byte-identical still produces a
    /// new version. Provenance-only fields are excluded so a redeploy does not manufacture a
    /// version.
    /// </summary>
    public static string DerivePolicyVersion(Policy policy)
    {
        var resolved = Canonicalizer.CanonicalizeObject(new Dictionary<string, object?>
        {
            ["rungs"] = policy.Rungs.ToDictionary(
                kv => kv.Key,
                kv => (object?)$"{kv.Value.RequiredSigners}/{kv.Value.DistinctIdentities}/" +
                      $"{kv.Value.Proposable}/{kv.Value.MinSeniority}/" +
                      string.Join(",", kv.Value.SignerRoles) + "|" +
                      string.Join(",", kv.Value.CosignerRoles)),
            ["thresholds"] = policy.Thresholds.ToDictionary(kv => kv.Key, kv => (object?)kv.Value),
            ["actions"] = policy.Actions.ToDictionary(
                kv => kv.Key,
                kv => (object?)($"{kv.Value.BaseRung}|{kv.Value.AgentMayPropose}|" +
                                string.Join(",", kv.Value.HashFields) + "|" +
                                string.Join(";", kv.Value.Thresholds.Select(RuleFingerprint)))),
            ["escalators"] = string.Join(";", policy.Escalators.Select(RuleFingerprint))
        });

        return "pv1:" + Canonicalizer.Sha256Hex(resolved)[..16];
    }

    /// <summary>
    /// ⚠️ FINDING F-6 (found by PolicyVersionBindingTests, 2026-05). The obvious implementation
    /// interpolates <c>r.When.Value</c> directly. For a JSON array that yields <c>JsonElement</c>'s
    /// RAW TEXT — newlines, indentation and all — so pretty-printing the policy file changes the
    /// policyVersion without changing a single rule.
    ///
    /// The consequence is not cosmetic. A new version makes the re-evaluation gate treat every
    /// in-flight approval as if the policy had moved; at best it churns, at worst someone
    /// "fixes" the noise by loosening the comparison. The fingerprint must be built from
    /// canonicalized VALUES, never from source text.
    /// </summary>
    private static string RuleFingerprint(Rule r) =>
        $"{r.Key}:{r.When.Field}:{r.When.Op}:{r.When.ValueRef}:{CanonicalRuleValue(r.When.Value)}:" +
        $"{r.RaiseTo}:{r.RaiseBy}:{r.MinRung}:{r.MinSigners}:{r.MinSeniority}";

    private static string CanonicalRuleValue(object? value) => value switch
    {
        null => "",
        JsonElement el => CanonicalJson(el),
        _ => value.ToString() ?? ""
    };

    private static string CanonicalJson(JsonElement el) => el.ValueKind switch
    {
        JsonValueKind.Array => "[" + string.Join(",", el.EnumerateArray().Select(CanonicalJson)) + "]",
        JsonValueKind.Object => "{" + string.Join(",", el.EnumerateObject()
            .OrderBy(p => p.Name, StringComparer.Ordinal)
            .Select(p => $"{p.Name}:{CanonicalJson(p.Value)}")) + "}",
        JsonValueKind.String => el.GetString() ?? "",
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        _ => el.GetRawText().Trim()
    };
}
