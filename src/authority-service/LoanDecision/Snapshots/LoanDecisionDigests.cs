using System.Security.Cryptography;
using System.Text;
using System.Globalization;
using AuthorityService.LoanDecision.Contracts;
using AuthorityService.Models;
using AuthorityService.Policy;
using Newtonsoft.Json.Linq;

namespace AuthorityService.LoanDecision.Snapshots;

public static class LoanDecisionDigests
{
    public const string EvidenceDomain = "loan-evidence.v1";
    public const string SnapshotDomain = "loan-snapshot.v1";
    public const string PolicyResultDomain = "loan-policy-result.v1";
    public const string ActionDomain = "loan-action.v1";
    public const string ApprovalBindingDomain = "loan-approval-binding.v1";
    public const string AuthoritativeSourceDomain = "loan-authoritative-source.v1";

    public static string Evidence(LoanEvidenceItemV1 evidence) =>
        Hash(EvidenceDomain, JObject.FromObject(evidence, Serializer()));

    public static string Snapshot(LoanDecisionSnapshotV1 snapshot)
    {
        var token = JObject.FromObject(snapshot, Serializer());
        token.Remove("snapshotDigest");
        return Hash(SnapshotDomain, token);
    }

    public static string PolicyResult(LoanDecisionOracleResultV1 result)
    {
        var token = JObject.FromObject(result, Serializer());
        token.Remove("resultDigest");
        return Hash(PolicyResultDomain, token);
    }

    public static string Action(LoanActionBindingV1 action)
    {
        var token = JObject.FromObject(action, Serializer());
        token.Remove("actionDigest");
        return Hash(ActionDomain, token);
    }

    public static string ApprovalBinding(LoanDecisionBindingV1 binding)
    {
        var token = JObject.FromObject(binding, Serializer());
        token.Remove("approvalBindingDigest");
        return Hash(ApprovalBindingDomain, token);
    }

    public static string AuthoritativeSource(LoanDecisionSnapshotV1 snapshot) =>
        Hash(AuthoritativeSourceDomain, JObject.FromObject(new
        {
            snapshot.Sources,
            snapshot.Documents,
            snapshot.Evidence,
            snapshot.Completeness,
            snapshot.Freshness,
            snapshot.Contradictions,
            snapshot.Facts
        }, Serializer()));

    private static Newtonsoft.Json.JsonSerializer Serializer() =>
        Newtonsoft.Json.JsonSerializer.Create(LoanContractSerialization.Settings);

    private static string Hash(string domain, JToken value)
    {
        NormalizeDates(value);
        var canonical = Canonicalizer.Canonicalize(value);
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(domain + "\n" + canonical));
        return "sha256:" + Convert.ToHexString(digest).ToLowerInvariant();
    }

    private static void NormalizeDates(JToken token)
    {
        foreach (var child in token.Children().ToList())
            NormalizeDates(child);

        if (token is not JValue { Type: JTokenType.Date } value) return;

        var timestamp = value.Value switch
        {
            DateTimeOffset offset => offset,
            DateTime dateTime => new DateTimeOffset(dateTime),
            _ => throw new CanonicalizationException("A date token did not contain a date value.")
        };
        value.Value = timestamp.ToUniversalTime()
            .ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
    }
}
