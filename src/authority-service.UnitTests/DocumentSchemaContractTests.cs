using System.Text.RegularExpressions;
using AuthorityService.Models;
using FluentAssertions;
using Newtonsoft.Json.Linq;
using Xunit;
using Xunit.Abstractions;

namespace AuthorityService.UnitTests;

/// <summary>
/// Design §5.3.1b — the shape contract, enforced as a set of dotted field paths.
///
/// §5.3.1a compared identifier NAMES across documents and could not have caught the drift Rusty
/// found: <c>createdAt</c> and <c>proposedAtUtc</c> are each perfectly consistent inside their own
/// document, so there is no shared name spelled two ways to grep for. What diverged was the SET
/// of paths, and a set difference is not a substring search.
///
/// This is the .NET half, and it is the only check that can see a serializer naming-policy
/// mismatch: it compares a document the service actually wrote against the canonical block in the
/// design doc. Cosmos returns ZERO ROWS rather than an error on a path mismatch, so this failure
/// mode does not announce itself anywhere else.
/// </summary>
public class DocumentSchemaContractTests
{
    private readonly ITestOutputHelper _output;

    public DocumentSchemaContractTests(ITestOutputHelper output) => _output = output;

    /// <summary>
    /// Open-content subtrees: caller-supplied or policy-derived maps whose keys are data, not
    /// schema. The path to the container is contractual; what is inside it is not.
    /// </summary>
    private static readonly string[] OpaqueSubtrees =
    [
        "payload", "evidence", "facts", "agentAssessment", "terminalDetail",
        "target.pathParams", "policy.resolvedThresholdSnapshot"
    ];

    [Fact]
    public void A_document_the_service_actually_wrote_equals_the_canonical_path_set()
    {
        var canonical = CanonicalPaths();
        var actual = ActualPaths();

        var missing = canonical.Except(actual).OrderBy(p => p, StringComparer.Ordinal).ToList();
        var extra = actual.Except(canonical).OrderBy(p => p, StringComparer.Ordinal).ToList();

        if (missing.Count > 0 || extra.Count > 0)
        {
            _output.WriteLine("In the design doc but never written: " + string.Join(", ", missing));
            _output.WriteLine("Written but not in the design doc: " + string.Join(", ", extra));
        }

        missing.Should().BeEmpty(
            "design §5.3 promises a field the service never writes — a reader would query it and " +
            "get nothing back, with no error");

        extra.Should().BeEmpty(
            "the service writes a field the design doc does not declare — the design doc is the " +
            "single source for this shape (Danny, 2026-09-04), so the doc must be updated rather " +
            "than the field left undocumented");
    }

    [Fact]
    public void Nulls_are_written_rather_than_omitted()
    {
        // A field dropped for being null is invisible to a path-set comparison AND changes how
        // Cosmos evaluates a predicate on it. Both failure modes are silent.
        var json = JObject.Parse(ApprovalSerialization.Serialize(new Approval()));

        json.Property("terminalReason").Should().NotBeNull();
        json["terminalReason"]!.Type.Should().Be(JTokenType.Null);
    }

    [Fact]
    public void No_field_is_camel_cased_by_a_naming_policy_rather_than_declared()
    {
        // Every property carries an explicit [JsonProperty]. If one ever loses its attribute, a
        // naming policy would quietly rename it; without a naming policy it appears PascalCased
        // here and fails the equality test above rather than silently renaming a Cosmos path.
        var json = JObject.Parse(ApprovalSerialization.Serialize(new Approval()));

        foreach (var property in json.Properties())
        {
            var name = property.Name.TrimStart('_');

            char.IsLower(name[0]).Should().BeTrue(
                $"'{property.Name}' is not declared with an explicit camelCase [JsonProperty]");
        }
    }

    // -----------------------------------------------------------------------------------

    private static SortedSet<string> CanonicalPaths()
    {
        var markdown = File.ReadAllText(DesignDocPath());
        var start = markdown.IndexOf("### 5.3 Document schema", StringComparison.Ordinal);

        start.Should().BeGreaterThan(0, "design §5.3 is the authoritative schema and must exist");

        var section = markdown[start..markdown.IndexOf("### 5.3.1 ", start, StringComparison.Ordinal)];
        var fence = Regex.Match(section, "```jsonc\\r?\\n(.*?)```", RegexOptions.Singleline);

        fence.Success.Should().BeTrue("design §5.3 must carry the canonical document as a jsonc block");

        var body = StripComments(fence.Groups[1].Value);
        var document = JObject.Parse(body);

        return Flatten(document);
    }

    private static SortedSet<string> ActualPaths()
    {
        var harness = TestHarness.Build();
        var paths = new SortedSet<string>(StringComparer.Ordinal);

        foreach (var json in RealDocuments(harness))
        {
            paths.UnionWith(Flatten(JObject.Parse(json)));
        }

        return paths;
    }

    /// <summary>
    /// Documents produced by driving the real service, not hand-built objects — the point is to
    /// catch what the write path actually emits.
    /// </summary>
    private static List<string> RealDocuments(TestHarness.Harness harness)
    {
        var banker = TestHarness.Banker();
        var supervisor = TestHarness.Supervisor();
        var documents = new List<string>();

        // 1. An L1 approval carried all the way through execution.
        var executed = harness.Service.ProposeAsync(TestHarness.FlagReview("100.00"), banker, null)
            .GetAwaiter().GetResult();
        harness.Service.SignAsync(executed.Id, banker, new Contracts.SignRequest(), "jti-1")
            .GetAwaiter().GetResult();
        harness.Service.ExecuteAsync(executed.Id, banker, "token").GetAwaiter().GetResult();
        documents.Add(harness.Repository.RawDocument(executed.Id));

        // 2. An L2 approval — two slots, a fired escalator — denied, so the terminal fields and
        //    the retention `ttl` are populated too.
        var denied = harness.Service.ProposeAsync(TestHarness.FlagReview("250000.00"), banker, null)
            .GetAwaiter().GetResult();
        harness.Service.DenyAsync(denied.Id, supervisor,
                new Contracts.DenyRequest { Reason = "The customer confirmed this charge was authorised." })
            .GetAwaiter().GetResult();
        documents.Add(harness.Repository.RawDocument(denied.Id));

        return documents;
    }

    private static SortedSet<string> Flatten(JObject root)
    {
        var paths = new SortedSet<string>(StringComparer.Ordinal);

        void Walk(JToken token, string prefix)
        {
            switch (token)
            {
                case JObject obj:
                    foreach (var property in obj.Properties())
                    {
                        var path = prefix.Length == 0 ? property.Name : prefix + "." + property.Name;

                        paths.Add(path);

                        if (!OpaqueSubtrees.Contains(path, StringComparer.Ordinal))
                        {
                            Walk(property.Value, path);
                        }
                    }

                    break;

                case JArray array:
                    foreach (var element in array)
                    {
                        Walk(element, prefix + "[]");
                    }

                    break;
            }
        }

        Walk(root, string.Empty);

        return paths;
    }

    private static string StripComments(string jsonc)
    {
        var cleaned = new List<string>();

        foreach (var line in jsonc.Split('\n'))
        {
            var inString = false;
            var end = line.Length;

            for (var i = 0; i < line.Length; i++)
            {
                if (line[i] == '"' && (i == 0 || line[i - 1] != '\\')) inString = !inString;

                if (!inString && line[i] == '/' && i + 1 < line.Length && line[i + 1] == '/')
                {
                    end = i;
                    break;
                }
            }

            cleaned.Add(line[..end]);
        }

        var body = string.Join('\n', cleaned)
            .Replace("[ ... ]", "[]", StringComparison.Ordinal)
            .Replace("...", string.Empty, StringComparison.Ordinal);

        // Trailing commas left behind by the elided examples.
        return Regex.Replace(body, ",(\\s*[}\\]])", "$1");
    }

    private static string DesignDocPath()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);

        while (directory is not null)
        {
            var candidate = Path.Combine(
                directory.FullName, "docs", "design", "banker-copilot-policy-engine.md");

            if (File.Exists(candidate)) return candidate;

            directory = directory.Parent;
        }

        throw new FileNotFoundException("Could not locate the design doc from the test output directory.");
    }
}
