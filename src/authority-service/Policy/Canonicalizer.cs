using System.Globalization;
using System.Text;
using System.Text.Json;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Policy;

/// <summary>
/// Thrown when a payload cannot be canonicalized. Always a 400/422 at the API surface — never
/// a coercion. A value we cannot canonicalize is a value a human cannot be said to have signed.
/// </summary>
public class CanonicalizationException : Exception
{
    public CanonicalizationException(string message) : base(message) { }
}

/// <summary>
/// RFC 8785 (JCS) canonicalization with the two deliberate deviations for money described in
/// design §6.2:
///
/// <list type="number">
/// <item>Object keys sorted by UTF-16 code unit, ascending.</item>
/// <item>No insignificant whitespace; separators are exactly <c>,</c> and <c>:</c>.</item>
/// <item>Strings JSON-escaped minimally, UTF-8, NFC-normalized.</item>
/// <item><b>Deviation:</b> money is a fixed-scale decimal STRING, never an ES6 double.
///       Non-money numbers must be integers. Floats in a money position are rejected.</item>
/// <item>Explicit <c>null</c> and absent are indistinguishable — both omitted.</item>
/// <item>Arrays preserve order.</item>
/// <item>Nested objects recurse; <c>hashFields</c> may name dotted paths.</item>
/// <item>A declared field that cannot be supplied is a hard error, never silently skipped.</item>
/// </list>
/// </summary>
public static class Canonicalizer
{
    public static string Canonicalize(JToken token)
    {
        var sb = new StringBuilder();
        Write(token, sb, moneyPaths: null, path: string.Empty, scale: 0);
        return sb.ToString();
    }

    public static string Canonicalize(JToken token, IReadOnlySet<string> moneyPaths, int currencyScale)
    {
        var sb = new StringBuilder();
        Write(token, sb, moneyPaths, path: string.Empty, scale: currencyScale);
        return sb.ToString();
    }

    /// <summary>
    /// Projects a payload onto the declared <c>hashFields</c>, in the order declared, preserving
    /// dotted paths as nested structure. Projecting explicitly is what makes "what did the human
    /// actually agree to?" a reviewable list in the policy file (design §6.1).
    /// </summary>
    public static JObject Project(JObject payload, IReadOnlyList<string> hashFields)
    {
        var projected = new JObject();

        foreach (var field in hashFields)
        {
            var value = ResolvePath(payload, field);

            if (value is null || value.Type == JTokenType.Null)
            {
                // Rule 5: explicit null and absent are indistinguishable, and both are omitted.
                continue;
            }

            SetPath(projected, field, value.DeepClone());
        }

        return projected;
    }

    /// <summary>
    /// Verifies that every declared hash field which is NOT nullable-by-omission is present.
    /// A payload that cannot supply a declared field is malformed (design §6.2 rule 8) — but
    /// rule 5 makes omission legal, so this only rejects structurally impossible paths
    /// (a path that traverses through a non-object).
    /// </summary>
    public static void AssertProjectable(JObject payload, IReadOnlyList<string> hashFields)
    {
        foreach (var field in hashFields)
        {
            var segments = field.Split('.');
            JToken? cursor = payload;

            foreach (var segment in segments)
            {
                if (cursor is null || cursor.Type == JTokenType.Null) break;

                if (cursor is not JObject obj)
                {
                    throw new CanonicalizationException(
                        $"Hash field '{field}' cannot be projected: '{segment}' is reached through " +
                        "a non-object value. The payload does not match the action's declared shape.");
                }

                cursor = obj[segment];
            }

            // A declared hash field must be PRESENT. Treating an absent field as "nothing to
            // hash" would let `{amount omitted}` and `{amount: 0}` produce different approvals
            // that a signer cannot tell apart.
            if (cursor is null || cursor.Type == JTokenType.Null)
            {
                throw new CanonicalizationException(
                    $"Hash field '{field}' is missing from the payload. Every field this action " +
                    "signs over must be supplied.");
            }
        }
    }

    private static JToken? ResolvePath(JObject root, string dottedPath)
    {
        JToken? cursor = root;

        foreach (var segment in dottedPath.Split('.'))
        {
            if (cursor is not JObject obj) return null;
            cursor = obj[segment];
        }

        return cursor;
    }

    private static void SetPath(JObject root, string dottedPath, JToken value)
    {
        var segments = dottedPath.Split('.');
        var cursor = root;

        for (var i = 0; i < segments.Length - 1; i++)
        {
            if (cursor[segments[i]] is JObject next)
            {
                cursor = next;
            }
            else
            {
                var created = new JObject();
                cursor[segments[i]] = created;
                cursor = created;
            }
        }

        cursor[segments[^1]] = value;
    }

    private static void Write(JToken token, StringBuilder sb, IReadOnlySet<string>? moneyPaths, string path, int scale)
    {
        switch (token.Type)
        {
            case JTokenType.Object:
                WriteObject((JObject)token, sb, moneyPaths, path, scale);
                break;

            case JTokenType.Array:
                WriteArray((JArray)token, sb, moneyPaths, path, scale);
                break;

            case JTokenType.Boolean:
                sb.Append((bool)((JValue)token).Value! ? "true" : "false");
                break;

            case JTokenType.String:
                WriteString(MaybeMoney((JValue)token, moneyPaths, path, scale), sb);
                break;

            case JTokenType.Integer:
            case JTokenType.Float:
                WriteNumber((JValue)token, sb, moneyPaths, path, scale);
                break;

            case JTokenType.Null:
                // Unreachable for projected payloads (nulls are omitted), but a nested null
                // inside an array is representable. Canonicalize it as JSON null.
                sb.Append("null");
                break;

            default:
                throw new CanonicalizationException(
                    $"Value at '{(path.Length == 0 ? "<root>" : path)}' has unsupported JSON type " +
                    $"'{token.Type}' and cannot be canonicalized.");
        }
    }

    private static void WriteObject(JObject obj, StringBuilder sb, IReadOnlySet<string>? moneyPaths, string path, int scale)
    {
        // Rule 1: keys sorted by UTF-16 code unit, ascending. Ordinal comparison in .NET is
        // exactly a UTF-16 code unit comparison.
        var properties = obj.Properties()
            .Where(p => p.Value.Type != JTokenType.Null)   // rule 5
            .OrderBy(p => p.Name, StringComparer.Ordinal)
            .ToList();

        sb.Append('{');

        for (var i = 0; i < properties.Count; i++)
        {
            if (i > 0) sb.Append(',');

            WriteString(properties[i].Name, sb);
            sb.Append(':');

            var childPath = path.Length == 0 ? properties[i].Name : $"{path}.{properties[i].Name}";
            Write(properties[i].Value, sb, moneyPaths, childPath, scale);
        }

        sb.Append('}');
    }

    private static void WriteArray(JArray array, StringBuilder sb, IReadOnlySet<string>? moneyPaths, string path, int scale)
    {
        sb.Append('[');

        for (var i = 0; i < array.Count; i++)
        {
            if (i > 0) sb.Append(',');
            Write(array[i], sb, moneyPaths, path, scale);
        }

        sb.Append(']');
    }

    private static string MaybeMoney(JValue value, IReadOnlySet<string>? moneyPaths, string path, int scale)
    {
        var raw = value.Value?.ToString() ?? string.Empty;

        if (moneyPaths is null || !moneyPaths.Contains(path)) return NormalizeNfc(raw);

        if (!decimal.TryParse(raw, NumberStyles.Number, CultureInfo.InvariantCulture, out var amount))
        {
            throw new CanonicalizationException(
                $"Money field '{path}' has value '{raw}', which is not a decimal.");
        }

        return FormatMoney(amount, scale, path);
    }

    private static void WriteNumber(JValue value, StringBuilder sb, IReadOnlySet<string>? moneyPaths, string path, int scale)
    {
        var isMoney = moneyPaths is not null && moneyPaths.Contains(path);

        if (isMoney)
        {
            // Rule 4: a JSON float in a money position is rejected outright, never coerced.
            // An integer is accepted because it carries no precision ambiguity.
            if (value.Type == JTokenType.Float)
            {
                throw new CanonicalizationException(
                    $"Money field '{path}' is a JSON number with a fractional part. Money must be " +
                    "supplied as a decimal string (for example \"7500.50\") so that 7500.00, " +
                    "7500.0 and 7.5e3 cannot mean three different things.");
            }

            var amount = Convert.ToDecimal(value.Value, CultureInfo.InvariantCulture);
            WriteString(FormatMoney(amount, scale, path), sb);
            return;
        }

        if (value.Type == JTokenType.Float)
        {
            throw new CanonicalizationException(
                $"Field '{path}' is a floating-point number. Non-money numbers must be integers; " +
                "anything with a fractional part must be supplied as a string.");
        }

        sb.Append(Convert.ToInt64(value.Value, CultureInfo.InvariantCulture)
            .ToString(CultureInfo.InvariantCulture));
    }

    private static string FormatMoney(decimal amount, int scale, string path)
    {
        var rounded = Math.Round(amount, scale, MidpointRounding.ToEven);

        if (rounded != amount)
        {
            throw new CanonicalizationException(
                $"Money field '{path}' carries more precision than the configured currency scale " +
                $"of {scale}. Refusing to round a figure a human is being asked to sign.");
        }

        return rounded.ToString("F" + scale.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
    }

    private static string NormalizeNfc(string value) => value.Normalize(NormalizationForm.FormC);

    /// <summary>
    /// JCS escapes only <c>"</c>, <c>\</c> and the C0 control characters (with the short forms
    /// <c>\b \t \n \f \r</c>); everything else stays literal UTF-8. The relaxed encoder is what
    /// gives that — the default encoder would emit <c>\uXXXX</c> for every non-ASCII character,
    /// which is valid JSON but NOT canonical, and would silently produce a different hash for
    /// the same payload depending on the writer.
    /// </summary>
    private static readonly JsonSerializerOptions MinimalEscaping = new()
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    private static void WriteString(string value, StringBuilder sb)
    {
        sb.Append(JsonSerializer.Serialize(NormalizeNfc(value), MinimalEscaping));
    }
}
