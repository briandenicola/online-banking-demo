using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Policy;

/// <summary>
/// Computes the payload hash a signature binds to (design §6.2).
///
/// <code>
/// canonical = JCS_MODIFIED(project(payload, action.hashFields))
/// payloadHash = "sha256:" + hex(SHA256("bcp.v2\n" + actionId + "\n" + policyVersion + "\n" + canonical))
/// </code>
///
/// The domain-separation prefix means an identical payload under a different action — or under
/// a different ruleset — produces a different hash. A signature for one action can never be
/// replayed against another, and a signature produced under a permissive policy can never be
/// presented as though it were produced under the current one.
/// </summary>
public static class PayloadHasher
{
    public static string Compute(
        JObject payload,
        ActionDefinition action,
        string actionId,
        string policyVersion,
        int currencyScale)
    {
        var canonical = CanonicalProjection(payload, action, currencyScale);

        var preimage = new StringBuilder()
            .Append(SharedIdentifiers.CanonicalizationScheme).Append('\n')
            .Append(actionId).Append('\n')
            .Append(policyVersion).Append('\n')
            .Append(canonical)
            .ToString();

        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(preimage));

        return "sha256:" + Convert.ToHexString(digest).ToLowerInvariant();
    }

    public static string CanonicalProjection(JObject payload, ActionDefinition action, int currencyScale)
    {
        Canonicalizer.AssertProjectable(payload, action.HashFields);

        var projection = Canonicalizer.Project(payload, action.HashFields);
        var moneyPaths = action.MoneyFields.ToHashSet(StringComparer.Ordinal);

        return Canonicalizer.Canonicalize(projection, moneyPaths, currencyScale);
    }

    /// <summary>
    /// The display form. Produced by the server, never by the client — the UI must not be in
    /// the business of truncating a security value, and a server-owned display form means the
    /// grouping can change without a client release (design §8.5.1).
    /// </summary>
    public static string Short(string payloadHash)
    {
        var hex = payloadHash.StartsWith("sha256:", StringComparison.Ordinal)
            ? payloadHash["sha256:".Length..]
            : payloadHash;

        if (hex.Length < 16) return hex;

        return string.Join(' ', Enumerable.Range(0, 4).Select(i => hex.Substring(i * 4, 4)));
    }
}
