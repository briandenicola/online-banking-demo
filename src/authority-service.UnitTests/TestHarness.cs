using AuthorityService;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Newtonsoft.Json.Linq;

namespace AuthorityService.UnitTests;

/// <summary>
/// Builds a fully wired ApprovalService over the in-memory backend. Deliberately uses the REAL
/// policy file from <c>config/authority-policy.yaml</c> — a test suite that invents its own
/// policy proves the engine works on a policy nobody ships.
/// </summary>
public static class TestHarness
{
    public static string PolicyPath
    {
        get
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);

            while (directory is not null)
            {
                var candidate = Path.Combine(directory.FullName, "config", "authority-policy.yaml");

                if (File.Exists(candidate)) return candidate;

                directory = directory.Parent;
            }

            throw new FileNotFoundException("Could not locate config/authority-policy.yaml from the test output.");
        }
    }

    public static IConfiguration Configuration(params (string Key, string Value)[] overrides)
    {
        var settings = new Dictionary<string, string?>
        {
            ["Approval:SigningKey"] = "unit-test-authority-signing-key-not-the-jwt-key",
            ["Approval:RetentionSeconds"] = "7776000",
            ["Approval:SweepIntervalSeconds"] = "60",
            ["Approval:SweepBatchSize"] = "100",
            ["Denial:ReasonMinLength"] = "20",
            ["Denial:ReasonMaxLength"] = "2000",
            ["Denial:ReasonMinDistinctChars"] = "5",
            ["Denial:ReasonMaxRepeatUnit"] = "8",
            ["Denial:ReasonMinLetters"] = "10"
        };

        foreach (var (key, value) in overrides) settings[key] = value;

        return new ConfigurationBuilder().AddInMemoryCollection(settings).Build();
    }

    /// <summary>
    /// Reads the shipped policy and applies a textual mutation, FAILING if the text to replace is
    /// not present. A silent no-op here is the worst possible test outcome: the test would load an
    /// unmutated policy, see no exception, and report that an invariant holds when it was never
    /// challenged. Every negative policy test goes through this.
    /// </summary>
    public static string MutatedPolicyYaml(string find, string replace)
    {
        var yaml = File.ReadAllText(PolicyPath);

        if (!yaml.Contains(find, StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"The policy file no longer contains the text this test mutates:\n{find}\n" +
                "Update the test — do not let it pass by mutating nothing.");
        }

        return yaml.Replace(find, replace, StringComparison.Ordinal);
    }

    public static ResolvedPolicy LoadPolicy(params (string Key, string Value)[] overrides) =>
        PolicyLoader.FromConfiguration(Configuration(overrides)).LoadFromFile(PolicyPath);

    public static Harness Build(params (string Key, string Value)[] overrides)
    {
        var configuration = Configuration(overrides);
        var policy = PolicyLoader.FromConfiguration(configuration).LoadFromFile(PolicyPath);
        var provider = new PolicyProvider(policy);
        var repository = new InMemoryApprovalRepository(configuration);
        var audit = new NullAuditPublisher();
        var broker = new FakeActionBroker();

        var service = new ApprovalService(
            repository,
            provider,
            new PolicyEvaluator(),
            new HmacSignatureService(configuration),
            new DenialReasonValidator(configuration),
            audit,
            broker,
            NullLogger<ApprovalService>.Instance);

        return new Harness(service, repository, provider, audit, broker, configuration);
    }

    public record Harness(
        ApprovalService Service,
        InMemoryApprovalRepository Repository,
        PolicyProvider Policies,
        NullAuditPublisher Audit,
        FakeActionBroker Broker,
        IConfiguration Configuration);

    // ---- Canonical actors ----------------------------------------------------------------

    public static ActorContext Banker(string id = "banker-1", string? sessionId = "sess-1") => new()
    {
        UserId = id,
        Username = id,
        Role = "banker",
        EffectiveRoles = ["banker"],
        Seniority = 1,
        SessionId = sessionId
    };

    public static ActorContext Supervisor(string id = "supervisor-1") => new()
    {
        UserId = id,
        Username = id,
        Role = "supervisor",
        EffectiveRoles = ["supervisor"],
        Seniority = 2
    };

    /// <summary>
    /// A principal built the way the SERVICE builds one — seniority derived from role claims
    /// through the shipped policy — rather than asserted by the test. A test that hands itself a
    /// seniority is testing arithmetic; this one tests the mapping that was actually wrong.
    /// </summary>
    public static ActorContext FromClaims(string id, ResolvedPolicy policy, params string[] roles) => new()
    {
        UserId = id,
        Username = id,
        Role = roles.FirstOrDefault(),
        EffectiveRoles = roles,
        Seniority = policy.SeniorityForRoles(roles),
        SessionId = "sess-1"
    };

    // ---- Canonical payloads ---------------------------------------------------------------

    /// <summary>
    /// A flagged-transaction review that lands at L1 with the shipped thresholds. Amount is
    /// supplied by the caller so tests can straddle the dual-control limit without restating it.
    /// </summary>
    public static Contracts.ProposeRequest FlagReview(string amount, string decision = "cleared") => new()
    {
        ActionId = "transaction.flag.review",
        Payload = new JObject
        {
            ["transactionId"] = "txn-100",
            ["amount"] = amount,
            ["decision"] = decision,
            ["note"] = "Reviewed against the account's 90-day pattern."
        },
        Evidence = new JObject
        {
            ["get_flagged_transaction"] = new JObject
            {
                ["transactionId"] = "txn-100",
                ["amount"] = amount
            },
            ["list_account_transactions"] = new JObject
            {
                ["accountId"] = "acct-1",
                ["count"] = 42
            }
        },
        SessionId = "sess-1"
    };
}

public class FakeActionBroker : IActionBroker
{
    public List<Models.Approval> Calls { get; } = [];
    public BrokerResult Result { get; set; } = new(true, 200, "downstream-ref-1", null);

    public Task<BrokerResult> ExecuteAsync(
        Models.Approval approval, string? bearerToken, CancellationToken ct = default)
    {
        Calls.Add(approval);
        return Task.FromResult(Result);
    }
}
