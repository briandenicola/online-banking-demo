using System.Security.Cryptography;
using System.Text;
using AuthorityService.Policy;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace AuthorityService.LoanDecision.Policy;

public sealed class LoanPolicyLoader
{
    public const string UnresolvedReasonCode = "POLICY_DEFINITION_UNRESOLVED";

    public static readonly IReadOnlySet<string> RequiredRuleIds =
        Enumerable.Range(1, 10)
            .Select(number => $"POL-{number:000}")
            .ToHashSet(StringComparer.Ordinal);

    public ResolvedLoanPolicy LoadFromFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new LoanPolicyValidationException(
                "LOAN_UNDERWRITING_POLICY_FILE_PATH is required. Loan underwriting remains blocked.");
        }

        if (!File.Exists(path))
        {
            throw new LoanPolicyValidationException(
                $"Loan policy file '{path}' does not exist. Loan underwriting remains blocked.");
        }

        return LoadFromYaml(File.ReadAllText(path), path);
    }

    public ResolvedLoanPolicy LoadFromYaml(string yaml, string origin = "<inline>")
    {
        LoanPolicyDocument document;

        try
        {
            document = new DeserializerBuilder()
                .WithNamingConvention(CamelCaseNamingConvention.Instance)
                .Build()
                .Deserialize<LoanPolicyDocument>(yaml)
                ?? throw new LoanPolicyValidationException($"Loan policy file '{origin}' is empty.");
        }
        catch (LoanPolicyValidationException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new LoanPolicyValidationException(
                $"Loan policy file '{origin}' could not be parsed: {ex.Message}", ex);
        }

        Validate(document, origin);

        return new ResolvedLoanPolicy
        {
            Document = document,
            PolicyVersion = ComputeVersion(document),
            LoadedAt = DateTimeOffset.UtcNow
        };
    }

    private static void Validate(LoanPolicyDocument document, string origin)
    {
        var errors = new List<string>();

        if (document.ApiVersion != "loan-underwriting/v1")
            errors.Add($"apiVersion must be 'loan-underwriting/v1'; found '{document.ApiVersion}'.");

        if (string.IsNullOrWhiteSpace(document.Metadata.PolicyId))
            errors.Add("metadata.policyId is required.");

        var ids = document.Rules.Select(rule => rule.Id).ToList();
        foreach (var duplicate in ids.GroupBy(id => id, StringComparer.Ordinal).Where(group => group.Count() > 1))
            errors.Add($"Duplicate rule id '{duplicate.Key}'.");

        foreach (var missing in RequiredRuleIds.Except(ids, StringComparer.Ordinal).OrderBy(id => id))
            errors.Add($"Missing required rule id '{missing}'.");

        foreach (var unknown in ids.Except(RequiredRuleIds, StringComparer.Ordinal).OrderBy(id => id))
            errors.Add($"Unknown rule id '{unknown}'.");

        foreach (var duplicate in document.Rules
                     .Select(rule => rule.ReasonCode)
                     .GroupBy(code => code, StringComparer.Ordinal)
                     .Where(group => group.Count() > 1))
        {
            errors.Add($"Duplicate reasonCode '{duplicate.Key}'.");
        }

        foreach (var rule in document.Rules)
        {
            if (rule.Status != "PROVISIONAL")
                errors.Add($"{rule.Id}.status must be 'PROVISIONAL' until product-policy ratification.");

            if (rule.Operator != "UNDEFINED")
                errors.Add($"{rule.Id}.operator must be 'UNDEFINED' while the rule is provisional.");

            if (rule.Outcome != "BLOCKED")
                errors.Add($"{rule.Id}.outcome must be 'BLOCKED'; provisional rules cannot emit a decision.");

            if (rule.Outcome is "APPROVE" or "CONDITIONAL" or "DECLINE")
                errors.Add($"{rule.Id} is provisional and cannot emit {rule.Outcome}.");

            var expectedReasonCode = rule.Id.Replace("-", "_", StringComparison.Ordinal)
                                     + "_DEFINITION_UNRESOLVED";
            if (rule.ReasonCode != expectedReasonCode)
            {
                errors.Add(
                    $"{rule.Id}.reasonCode must be '{expectedReasonCode}' while the definition is unresolved.");
            }
        }

        if (errors.Count > 0)
        {
            throw new LoanPolicyValidationException(
                $"Loan policy file '{origin}' is invalid and underwriting remains blocked:{Environment.NewLine}" +
                string.Join(Environment.NewLine, errors.Select(error => "  - " + error)));
        }
    }

    private static string ComputeVersion(LoanPolicyDocument document)
    {
        var serializer = JsonSerializer.Create(new JsonSerializerSettings
        {
            ContractResolver = new CamelCasePropertyNamesContractResolver(),
            NullValueHandling = NullValueHandling.Include,
            Formatting = Formatting.None
        });
        var canonical = Canonicalizer.Canonicalize(JObject.FromObject(document, serializer));
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(canonical));
        return "lpv1:" + Convert.ToHexString(digest).ToLowerInvariant()[..16];
    }
}
