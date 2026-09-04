using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace BankerCopilotTests.Spec;

/// <summary>
/// JCS (RFC 8785) with the two money deviations specified in policy-engine §6.2:
///   4. money values are fixed-scale decimal strings; floats in a money position are rejected;
///   5. explicit-null and absent are indistinguishable by construction (both omitted).
/// Keys sort by UTF-16 code unit ascending; strings are NFC-normalized before hashing.
/// </summary>
public static class Canonicalizer
{
    public const string SchemeTag = "bcp.v2";
    public const string SignatureSchemeTag = "bcp-sig.v2";
    public const int CanonicalizationVersion = 2;

    public static string Sha256Hex(string s)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(s));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    /// <summary>
    /// Project the payload onto the action's declared hash fields, in policy-declared order,
    /// then canonicalize. §6.1: projecting explicitly makes "what did the human actually agree
    /// to?" a reviewable list rather than an emergent property of the serializer.
    /// </summary>
    public static string Project(IReadOnlyDictionary<string, object?> payload, ActionSpec action)
    {
        var projected = new Dictionary<string, object?>();

        foreach (var field in action.HashFields)
        {
            var present = TryResolvePath(payload, field, out var value);

            // Rule 5: explicit null is omitted, exactly as absent is. Indistinguishable by
            // construction — this removes the {"memo": null} vs {} ambiguity.
            if (!present || value is null)
            {
                // Rule 8: a missing DECLARED field is a hard error, never silently skipped.
                //
                // ⚠️ FINDING F-3 (found by PayloadHashTests, 2026-05). An earlier version of this
                // exempted money fields from the hard error. That exemption is the worst possible
                // one: dropping `amount` from a request would then produce the hash of a payload
                // with NO amount, and the attacker chooses the figure downstream. Money fields
                // need the check MORE than other fields, not less.
                //
                // Explicit-null is a different case and is handled below: it is omitted exactly
                // as absence is, removing the {"memo": null} vs {} ambiguity (rule 5).
                if (!present && !IsOptional(action, field))
                {
                    throw new CanonicalizationException(
                        $"Declared hash field '{field}' is missing from the payload. " +
                        "A payload that cannot supply a hash_fields entry is malformed (§6.2 rule 8).");
                }
                continue;
            }

            projected[field] = action.MoneyFields.Contains(field)
                ? CanonicalizeMoney(field, value, action.CurrencyScale)
                : CanonicalizeScalar(field, value);
        }

        return CanonicalizeObject(projected);
    }

    private static bool IsOptional(ActionSpec action, string field) => false;

    /// <summary>Rule 4. Money is a fixed-scale decimal STRING. Floats are rejected outright.</summary>
    private static string CanonicalizeMoney(string field, object value, int scale)
    {
        switch (value)
        {
            case double or float:
                throw new CanonicalizationException(
                    $"Money field '{field}' carries a floating-point value. Floats in a money " +
                    "position are a 400, not a coercion (§6.2 rule 4).");
            case decimal d:
                return d.ToString("F" + scale, CultureInfo.InvariantCulture);
            case int or long:
                return Convert.ToDecimal(value).ToString("F" + scale, CultureInfo.InvariantCulture);
            case string s when decimal.TryParse(s, NumberStyles.Number, CultureInfo.InvariantCulture, out var parsed):
                return parsed.ToString("F" + scale, CultureInfo.InvariantCulture);
            default:
                throw new CanonicalizationException(
                    $"Money field '{field}' carries a non-numeric value '{value}'.");
        }
    }

    private static object CanonicalizeScalar(string field, object value) => value switch
    {
        string s => s.Normalize(NormalizationForm.FormC),          // rule 3
        bool b => b,                                                // rule 5
        int or long => value,                                       // rule 4: integers only
        decimal d when decimal.Truncate(d) == d => (long)d,
        double or float => throw new CanonicalizationException(
            $"Non-money field '{field}' carries a float. Non-money numbers must be integers (§6.2 rule 4)."),
        IReadOnlyList<object?> list => list.Select(v => v is null ? null : CanonicalizeScalar(field, v)).ToList(),
        IReadOnlyDictionary<string, object?> nested => nested
            .Where(kv => kv.Value is not null)
            .ToDictionary(kv => kv.Key, kv => (object?)CanonicalizeScalar(field, kv.Value!)),
        _ => value.ToString()!.Normalize(NormalizationForm.FormC)
    };

    /// <summary>Rules 1, 2, 6, 7: sorted keys, no insignificant whitespace, arrays keep order.</summary>
    public static string CanonicalizeObject(IReadOnlyDictionary<string, object?> obj)
    {
        var sb = new StringBuilder();
        WriteObject(sb, obj);
        return sb.ToString();
    }

    private static void WriteObject(StringBuilder sb, IReadOnlyDictionary<string, object?> obj)
    {
        sb.Append('{');
        var first = true;

        // Rule 1: UTF-16 code unit ascending. StringComparer.Ordinal is exactly that.
        foreach (var key in obj.Keys.Where(k => obj[k] is not null).OrderBy(k => k, StringComparer.Ordinal))
        {
            if (!first) sb.Append(',');                              // rule 2
            first = false;
            WriteString(sb, key);
            sb.Append(':');                                          // rule 2
            WriteValue(sb, obj[key]);
        }

        sb.Append('}');
    }

    private static void WriteValue(StringBuilder sb, object? value)
    {
        switch (value)
        {
            case null:
                sb.Append("null");
                break;
            case string s:
                WriteString(sb, s);
                break;
            case bool b:
                sb.Append(b ? "true" : "false");
                break;
            case int or long:
                sb.Append(Convert.ToInt64(value).ToString(CultureInfo.InvariantCulture));
                break;
            case IReadOnlyDictionary<string, object?> nested:
                WriteObject(sb, nested);
                break;
            case System.Collections.IEnumerable seq:                 // rule 6: order is semantic
                sb.Append('[');
                var first = true;
                foreach (var item in seq)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteValue(sb, item);
                }
                sb.Append(']');
                break;
            default:
                WriteString(sb, value.ToString()!);
                break;
        }
    }

    private static void WriteString(StringBuilder sb, string s)
    {
        sb.Append(JsonSerializer.Serialize(s.Normalize(NormalizationForm.FormC)));
    }

    /// <summary>
    /// §6.2: payload_hash = "sha256:" + hex(SHA256("bcp.v2\n" + actionId + "\n" + policyVersion
    /// + "\n" + canonical_string)). policyVersion lives in the DOMAIN-SEPARATION PREFIX, not as a
    /// key inside the projection — otherwise a payload field literally named policyVersion could
    /// collide with it.
    /// </summary>
    public static string PayloadHash(
        IReadOnlyDictionary<string, object?> payload,
        string actionId,
        string policyVersion,
        ActionSpec action)
    {
        var canonical = Project(payload, action);
        var preimage = $"{SchemeTag}\n{actionId}\n{policyVersion}\n{canonical}";
        return "sha256:" + Sha256Hex(preimage);
    }

    /// <summary>
    /// §6.3 signing input. <c>slotOrdinal</c> is load-bearing: without it a captured signature
    /// could be replayed into the second slot, defeating dual control even though the identities
    /// differ.
    /// </summary>
    public static string SigningInput(
        string approvalId,
        string actionId,
        string policyVersion,
        string payloadHash,
        string signerUserId,
        string signerTokenJti,
        int slotOrdinal,
        string signedAtRfc3339,
        string nonce) =>
        string.Join('\n',
            SignatureSchemeTag, approvalId, actionId, policyVersion, payloadHash,
            signerUserId, signerTokenJti, slotOrdinal.ToString(CultureInfo.InvariantCulture),
            signedAtRfc3339, nonce);

    private static bool TryResolvePath(
        IReadOnlyDictionary<string, object?> root, string dottedPath, out object? value)
    {
        value = null;
        object? current = root;

        foreach (var segment in dottedPath.Split('.'))
        {
            if (current is IReadOnlyDictionary<string, object?> dict)
            {
                if (!dict.TryGetValue(segment, out current)) return false;
            }
            else
            {
                return false;
            }
        }

        value = current;
        return true;
    }
}

public sealed class CanonicalizationException(string message) : Exception(message);
