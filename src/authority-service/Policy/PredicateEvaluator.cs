using System.Globalization;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Policy;

/// <summary>
/// Evaluates one structured predicate against the evaluation document.
///
/// The predicate language is deliberately tiny and total: fixed operators, no loops, no
/// function calls, nothing to parse from user input. A predicate that cannot be evaluated is
/// FALSE — it never raises a rung by accident and never lowers one either, because the only
/// combinator upstream is <c>max</c>.
/// </summary>
public static class PredicateEvaluator
{
    public static bool Matches(PredicateDefinition predicate, JObject document, ResolvedPolicy policy)
    {
        var field = Resolve(document, predicate.Field);

        return predicate.Op switch
        {
            "exists" => field is not null && field.Type != JTokenType.Null,
            "isTrue" => AsBool(field) == true,
            "isFalse" => AsBool(field) == false,
            "empty" => IsEmpty(field),
            "notEmpty" => !IsEmpty(field),

            "eq" => Equals(field, predicate.Value),
            "ne" => field is not null && field.Type != JTokenType.Null && !Equals(field, predicate.Value),
            "in" => AsStrings(field).Any(v => (predicate.Values ?? []).Contains(v, StringComparer.Ordinal)),
            "notIn" => field is not null && field.Type != JTokenType.Null
                       && !AsStrings(field).Any(v => (predicate.Values ?? []).Contains(v, StringComparer.Ordinal)),
            "intersects" => AsStrings(field).Intersect(predicate.Values ?? [], StringComparer.Ordinal).Any(),

            "gte" => Compare(field, predicate, policy) is { } c && c >= 0,
            "gt" => Compare(field, predicate, policy) is { } c && c > 0,
            "lte" => Compare(field, predicate, policy) is { } c && c <= 0,
            "lt" => Compare(field, predicate, policy) is { } c && c < 0,
            "countGte" => CountOf(field) >= policy.Threshold(predicate.Threshold!).AsLong(),

            _ => false
        };
    }

    /// <summary>
    /// Resolves a dotted path against the document root, then — for the policy file's shorthand
    /// forms such as <c>decision</c> or <c>transfer.amount</c> — against the payload.
    /// </summary>
    public static JToken? Resolve(JObject document, string dottedPath)
    {
        var direct = ResolveIn(document, dottedPath);
        if (direct is not null) return direct;

        return document["payload"] is JObject payload ? ResolveIn(payload, dottedPath) : null;
    }

    private static JToken? ResolveIn(JObject root, string dottedPath)
    {
        JToken? cursor = root;

        foreach (var segment in dottedPath.Split('.'))
        {
            if (cursor is not JObject obj) return null;
            cursor = obj[segment];
        }

        return cursor is null || cursor.Type == JTokenType.Null ? null : cursor;
    }

    private static int? Compare(JToken? field, PredicateDefinition predicate, ResolvedPolicy policy)
    {
        var actual = AsDecimal(field);
        if (actual is null) return null;

        if (predicate.Abs) actual = Math.Abs(actual.Value);

        var threshold = policy.Threshold(predicate.Threshold!).AsDecimal();

        return decimal.Compare(actual.Value, threshold);
    }

    private static decimal? AsDecimal(JToken? token)
    {
        if (token is null) return null;

        return token.Type switch
        {
            JTokenType.Integer or JTokenType.Float => token.Value<decimal>(),
            JTokenType.String => decimal.TryParse(
                token.Value<string>(), NumberStyles.Number, CultureInfo.InvariantCulture, out var parsed)
                ? parsed
                : null,
            _ => null
        };
    }

    private static bool? AsBool(JToken? token) => token?.Type switch
    {
        JTokenType.Boolean => token.Value<bool>(),
        JTokenType.String => bool.TryParse(token.Value<string>(), out var parsed) ? parsed : null,
        _ => null
    };

    private static bool Equals(JToken? field, object? literal)
    {
        if (field is null || field.Type == JTokenType.Null) return false;

        if (literal is bool expected) return AsBool(field) == expected;

        var wanted = Convert.ToString(literal, CultureInfo.InvariantCulture);

        return wanted is not null
               && string.Equals(field.Value<string>(), wanted, StringComparison.Ordinal);
    }

    private static IEnumerable<string> AsStrings(JToken? token)
    {
        switch (token)
        {
            case null:
                yield break;

            case JArray array:
                foreach (var element in array)
                {
                    var value = element.Value<string>();
                    if (value is not null) yield return value;
                }

                break;

            default:
                var single = token.Value<string>();
                if (single is not null) yield return single;
                break;
        }
    }

    private static long CountOf(JToken? token) => token switch
    {
        JArray array => array.Count,
        null => 0,
        _ => token.Type == JTokenType.Null ? 0 : 1
    };

    private static bool IsEmpty(JToken? token) => token switch
    {
        null => true,
        JArray array => array.Count == 0,
        JObject obj => !obj.HasValues,
        _ => token.Type == JTokenType.Null || string.IsNullOrEmpty(token.Value<string>())
    };
}
