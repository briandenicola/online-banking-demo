using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using AuthorityService.Models;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;

namespace AuthorityService.Policy;

/// <summary>A single threshold after env-var resolution. The value is always carried as a string.</summary>
public class ResolvedThreshold
{
    public required string Name { get; init; }
    public required string Kind { get; init; }
    public required string Env { get; init; }
    public required string Value { get; init; }
    public required string Description { get; init; }
    public required bool OverriddenByEnv { get; init; }
    public int CurrencyScale { get; init; }

    public decimal AsDecimal() => decimal.Parse(Value, NumberStyles.Number, CultureInfo.InvariantCulture);
    public int AsInt() => int.Parse(Value, NumberStyles.Integer, CultureInfo.InvariantCulture);
    public long AsLong() => long.Parse(Value, NumberStyles.Integer, CultureInfo.InvariantCulture);
}

/// <summary>
/// The policy after threshold resolution — the object the evaluator actually reads.
///
/// <see cref="PolicyVersion"/> is a content hash of THIS object (design §6.2.1), not of the
/// file bytes: every threshold is env-overridable, so a ConfigMap edit is a genuine policy
/// change that leaves the YAML byte-identical. Hashing the file would report "no change" and
/// a signature produced under the old ruleset would keep validating under the new one.
/// </summary>
public class ResolvedPolicy
{
    public required PolicyDocument Document { get; init; }
    public required IReadOnlyDictionary<string, ResolvedThreshold> Thresholds { get; init; }
    public required string PolicyVersion { get; init; }
    public required DateTime LoadedAt { get; init; }

    public string PolicyId => Document.Metadata.PolicyId;

    public ResolvedThreshold Threshold(string name)
    {
        if (!Thresholds.TryGetValue(name, out var threshold))
        {
            // Fail closed. There is deliberately no code-level fallback value to fall back TO.
            throw new PolicyValidationException(
                $"Threshold '{name}' is referenced but not defined in the policy's thresholds block.");
        }

        return threshold;
    }

    public ActionDefinition? Action(string actionId) =>
        Document.ActionTypes.TryGetValue(actionId, out var action) ? action : null;

    public RungDefinition Rung(Rung rung)
    {
        var key = RungOrder.ToWire(rung);

        if (!Document.Rungs.TryGetValue(key, out var definition))
        {
            throw new PolicyValidationException($"Rung '{key}' is not defined in the policy file.");
        }

        return definition;
    }

    public int SeniorityForRole(string? role)
    {
        if (string.IsNullOrWhiteSpace(role)) return 0;

        var best = 0;

        foreach (var (_, definition) in Document.SignerRoles)
        {
            if (definition.ClaimValues.Contains(role, StringComparer.OrdinalIgnoreCase))
            {
                best = Math.Max(best, definition.Seniority);
            }
        }

        return best;
    }

    /// <summary>
    /// Lowest banking seniority among a set of named signer roles — i.e. the bar a slot open to
    /// those roles must set. Empty is fatal rather than 0: an unconstrained slot is one any
    /// authenticated principal fills.
    /// </summary>
    public int MinimumSeniorityAmong(IEnumerable<string> roleNames)
    {
        var levels = roleNames
            .Select(name => Document.SignerRoles.TryGetValue(name, out var role) ? role.Seniority : -1)
            .ToList();

        if (levels.Count == 0 || levels.Any(level => level < 1))
        {
            throw new PolicyValidationException(
                "A signature slot resolved to an empty or unranked role set. Refusing to compute a " +
                "seniority bar that every authenticated principal would clear.");
        }

        return levels.Min();
    }

    /// <summary>Highest seniority across all of a principal's effective roles.</summary>
    public int SeniorityForRoles(IEnumerable<string> roles) =>
        roles.Select(SeniorityForRole).DefaultIfEmpty(0).Max();

    /// <summary>
    /// Computes the content hash of a resolved policy. Excludes <c>metadata.effectiveFrom</c>
    /// and <c>metadata.owner</c> — provenance, not rules — so redeploying an unchanged ruleset
    /// with a new timestamp does not manufacture a new version.
    /// </summary>
    public static string ComputeVersion(
        PolicyDocument document,
        IReadOnlyDictionary<string, ResolvedThreshold> thresholds)
    {
        var serializer = JsonSerializer.Create(new JsonSerializerSettings
        {
            ContractResolver = new CamelCasePropertyNamesContractResolver(),
            NullValueHandling = NullValueHandling.Ignore,
            Formatting = Formatting.None
        });

        var snapshot = JObject.FromObject(document, serializer);

        if (snapshot["metadata"] is JObject metadata)
        {
            metadata.Remove("effectiveFrom");
            metadata.Remove("owner");
        }

        // Replace the threshold DEFINITIONS with their RESOLVED VALUES. This is the whole point:
        // the hash must move when POLICY_TRANSFER_L2_AMOUNT changes, even though the file did not.
        var resolved = new JObject();

        foreach (var name in thresholds.Keys.OrderBy(k => k, StringComparer.Ordinal))
        {
            resolved[name] = thresholds[name].Value;
        }

        snapshot["thresholds"] = resolved;

        var canonical = Canonicalizer.Canonicalize(snapshot);
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(canonical));

        return "pv1:" + Convert.ToHexString(digest).ToLowerInvariant()[..16];
    }
}
