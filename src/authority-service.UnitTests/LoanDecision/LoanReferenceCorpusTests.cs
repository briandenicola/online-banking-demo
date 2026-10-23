using FluentAssertions;
using Xunit;
using YamlDotNet.RepresentationModel;

namespace AuthorityService.UnitTests.LoanDecision;

public sealed class LoanReferenceCorpusTests
{
    [Fact]
    public void Independent_reference_interpreter_confirms_all_provisional_rules_block()
    {
        using var reader = File.OpenText(FindPolicy());
        var yaml = new YamlStream();
        yaml.Load(reader);
        var root = (YamlMappingNode)yaml.Documents.Single().RootNode;
        var rules = (YamlSequenceNode)root.Children[new YamlScalarNode("rules")];
        var reached = 0;

        foreach (var node in rules.Children.Cast<YamlMappingNode>())
        {
            reached++;
            Scalar(node, "status").Should().Be("PROVISIONAL");
            Scalar(node, "operator").Should().Be("UNDEFINED");
            Scalar(node, "outcome").Should().Be("BLOCKED");
            Scalar(node, "reasonCode").Should().Be(
                Scalar(node, "id").Replace("-", "_", StringComparison.Ordinal) +
                "_DEFINITION_UNRESOLVED");
        }

        reached.Should().Be(10, "Reached: an empty or partial corpus must not pass vacuously");
    }

    private static string Scalar(YamlMappingNode node, string key) =>
        ((YamlScalarNode)node.Children[new YamlScalarNode(key)]).Value!;

    private static string FindPolicy()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var path = Path.Combine(directory.FullName, "config", "loan-underwriting-policy.yaml");
            if (File.Exists(path)) return path;
            directory = directory.Parent;
        }
        throw new FileNotFoundException("Could not locate loan-underwriting-policy.yaml.");
    }
}
