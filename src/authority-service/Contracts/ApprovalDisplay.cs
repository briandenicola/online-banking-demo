using System.Globalization;
using System.Text.RegularExpressions;
using AuthorityService.Models;
using Newtonsoft.Json.Linq;

namespace AuthorityService.Contracts;

/// <summary>
/// Display-only approval enrichments. None of this enters the payload hash; it is derived from
/// already-stored payload/evidence so a card can name what was learned instead of dumping tool ids.
/// </summary>
public static partial class ApprovalDisplay
{
    public static JObject EnrichEvidence(JObject evidence)
    {
        var enriched = new JObject();

        foreach (var property in evidence.Properties())
        {
            if (property.Value is not JObject obj)
            {
                enriched[property.Name] = property.Value.DeepClone();
                continue;
            }

            var copy = (JObject)obj.DeepClone();
            if (copy["label"] is null) copy["label"] = EvidenceLabel(property.Name);
            if (copy["summary"] is null && EvidenceSummary(property.Name, copy) is { } summary)
            {
                copy["summary"] = summary;
            }

            enriched[property.Name] = copy;
        }

        return enriched;
    }

    public static ApprovalSubjectView? SubjectFor(Approval approval)
    {
        var payload = approval.Payload;
        var evidence = approval.Evidence;
        var user = evidence["get_user"] as JObject;
        var account = evidence["get_account"] as JObject;

        if (user is not null || payload["userId"] is not null)
        {
            var userId = Text(user?["userId"]) ?? Text(user?["id"]) ?? Text(payload["userId"]);
            var label = PersonName(user) ?? $"Customer record ····{Tail(userId)}";
            var status = Text(user?["status"]) ?? LockedStatus(user);

            return new ApprovalSubjectView
            {
                Kind = "customer",
                Label = label,
                Summary = status is null ? null : $"Status: {status}",
                UserId = userId,
                RiskTier = Text(user?["riskTier"])
            };
        }

        if (account is not null || payload["accountId"] is not null)
        {
            var accountId = Text(account?["accountId"]) ?? Text(account?["id"]) ?? Text(payload["accountId"]);
            var accountNumber = Text(account?["accountNumber"]);
            var accountType = Text(account?["accountType"]);
            var label = AccountLabel(accountType, accountNumber, accountId);

            return new ApprovalSubjectView
            {
                Kind = "account",
                Label = label,
                Summary = Money(account?["balance"]) is { } balance ? $"Balance {balance}" : null,
                UserId = Text(account?["userId"]),
                AccountId = accountId,
                AccountNumber = accountNumber,
                AccountType = accountType,
                RiskTier = Text(account?["riskTier"])
            };
        }

        return null;
    }

    private static string EvidenceLabel(string key) => key switch
    {
        "get_user" => "Customer record",
        "list_login_audits" => "Login history",
        "get_account" => "Account record",
        "list_account_transactions" => "Recent account activity",
        "get_flagged_transaction" => "Flagged transaction",
        "get_scored_transaction" => "AI score record",
        "get_transfer" => "Transfer record",
        "get_account_application" => "Account-opening application",
        "get_application_audit" => "Application audit trail",
        "get_loan_application" => "Loan application",
        "get_underwriting_decision" => "Underwriting decision",
        "get_underwriting_policy" => "Underwriting policy checks",
        _ => Humanize(key)
    };

    private static string? EvidenceSummary(string key, JObject value) => key switch
    {
        "get_user" => UserSummary(value),
        "list_login_audits" => CountSummary(value, "failed sign-in record", "failed sign-in records"),
        "get_account" => AccountSummary(value),
        "list_account_transactions" => CountSummary(value, "recent transaction", "recent transactions"),
        "get_flagged_transaction" => TransactionSummary(value),
        "get_scored_transaction" => ScoreSummary(value),
        "get_transfer" => TransferSummary(value),
        "get_account_application" => ApplicationSummary(value),
        "get_application_audit" => CountSummary(value, "audit event", "audit events", "events"),
        "get_loan_application" => LoanSummary(value),
        "get_underwriting_decision" => UnderwritingSummary(value),
        "get_underwriting_policy" => PolicySummary(value),
        _ => null
    };

    private static string? UserSummary(JObject value)
    {
        var name = PersonName(value) ?? $"Customer record ····{Tail(Text(value["userId"]) ?? Text(value["id"]))}";
        var status = Text(value["status"]) ?? LockedStatus(value);
        return status is null ? name : $"{name} is {status}";
    }

    private static string? AccountSummary(JObject value)
    {
        var label = AccountLabel(Text(value["accountType"]), Text(value["accountNumber"]),
            Text(value["accountId"]) ?? Text(value["id"]));
        return Money(value["balance"]) is { } balance ? $"{label}; balance {balance}" : label;
    }

    private static string? TransactionSummary(JObject value)
    {
        var amount = Money(value["amount"]);
        var risk = Text(value["riskScore"]);
        if (amount is not null && risk is not null) return $"{amount}; risk score {risk}";
        return amount ?? (risk is null ? null : $"Risk score {risk}");
    }

    private static string? ScoreSummary(JObject value)
    {
        var score = Text(value["riskScore"]) ?? Text(value["score"]);
        return score is null ? TransactionSummary(value) : $"Risk score {score}";
    }

    private static string? TransferSummary(JObject value) =>
        Money(value["amount"]) is { } amount ? $"Transfer amount {amount}" : null;

    private static string? ApplicationSummary(JObject value)
    {
        var status = Text(value["status"]);
        return status is null ? null : $"Application is {status}";
    }

    private static string? LoanSummary(JObject value) =>
        Money(value["amount"]) is { } amount ? $"Loan amount {amount}" : ApplicationSummary(value);

    private static string? UnderwritingSummary(JObject value)
    {
        var verdict = Text(value["verdict"]) ?? Text(value["decision"]);
        return verdict is null ? null : $"Underwriting verdict: {verdict}";
    }

    private static string? PolicySummary(JObject value)
    {
        if (value["policyExceptions"] is JArray array)
            return array.Count == 0 ? "No policy exceptions" : $"{array.Count} policy exception(s)";
        return null;
    }

    private static string? CountSummary(JObject value, string singular, string plural, string countArrayKey = "items")
    {
        var count = Long(value["count"]);
        if (count is null && value[countArrayKey] is JArray array) count = array.Count;
        return count is null ? null : $"{count.Value.ToString(CultureInfo.InvariantCulture)} {(count == 1 ? singular : plural)}";
    }

    private static string AccountLabel(string? accountType, string? accountNumber, string? accountId)
    {
        var suffix = Tail(accountNumber) ?? Tail(accountId);
        var type = string.IsNullOrWhiteSpace(accountType) ? "Account" : accountType;
        return suffix is null ? type : $"{type} account ····{suffix}";
    }

    private static string? PersonName(JObject? value)
    {
        if (value is null) return null;
        var first = Text(value["firstName"]);
        var last = Text(value["lastName"]);
        var full = string.Join(" ", new[] { first, last }.Where(s => !string.IsNullOrWhiteSpace(s)));
        if (!string.IsNullOrWhiteSpace(full)) return full;
        return Text(value["displayName"]) ?? Text(value["name"]) ?? Text(value["username"]) ?? Text(value["email"]);
    }

    private static string? LockedStatus(JObject? value)
    {
        if (value is null) return null;
        if (Bool(value["isLocked"]) == true) return "locked";
        if (Bool(value["isActive"]) == false) return "inactive";
        return null;
    }

    private static string? Money(JToken? token)
    {
        if (Decimal(token) is not { } amount) return null;
        return string.Create(CultureInfo.InvariantCulture, $"${amount:N2}");
    }

    private static decimal? Decimal(JToken? token)
    {
        if (token is null) return null;
        return token.Type switch
        {
            JTokenType.Integer or JTokenType.Float => token.Value<decimal>(),
            JTokenType.String => decimal.TryParse(token.Value<string>(), NumberStyles.Number, CultureInfo.InvariantCulture, out var parsed)
                ? parsed
                : null,
            _ => null
        };
    }

    private static long? Long(JToken? token)
    {
        if (token is null) return null;
        return token.Type switch
        {
            JTokenType.Integer => token.Value<long>(),
            JTokenType.Float => (long)token.Value<decimal>(),
            JTokenType.String => long.TryParse(token.Value<string>(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)
                ? parsed
                : null,
            _ => null
        };
    }

    private static bool? Bool(JToken? token) => token?.Type switch
    {
        JTokenType.Boolean => token.Value<bool>(),
        JTokenType.String => bool.TryParse(token.Value<string>(), out var parsed) ? parsed : null,
        _ => null
    };

    private static string? Text(JToken? token) =>
        token is null || token.Type == JTokenType.Null ? null : token.Value<string>();

    private static string? Tail(string? value)
    {
        var compact = value is null ? null : NonWord().Replace(value, "");
        if (string.IsNullOrWhiteSpace(compact)) return null;
        return compact.Length <= 4 ? compact : compact[^4..];
    }

    private static string Humanize(string key)
    {
        var spaced = key.Replace('_', ' ').Replace('-', ' ');
        return string.IsNullOrWhiteSpace(spaced)
            ? "Evidence"
            : char.ToUpperInvariant(spaced[0]) + spaced[1..];
    }

    [GeneratedRegex("[^A-Za-z0-9]")]
    private static partial Regex NonWord();
}
