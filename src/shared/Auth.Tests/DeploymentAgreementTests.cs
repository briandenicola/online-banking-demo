using Banking.Auth;
using FluentAssertions;
using Xunit;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

namespace Banking.Auth.Tests;

/// <summary>
/// Asserts that the deployment manifests AGREE with the registry rather than restating it.
///
/// This is the lesson from the escalation that lived for hours in the seam between two
/// independently-stated role models: every file was internally coherent and every test passed.
/// The .NET services derive their audience from the embedded registry, so they cannot drift —
/// but the Python services take theirs from an environment variable, and docker-compose and
/// kustomize each state it. Three statements of one value with nothing comparing them is
/// exactly how #334 happened. This test is the comparison.
/// </summary>
public class DeploymentAgreementTests
{
    private static readonly JwtAudienceRegistry Registry = JwtAudienceRegistry.Load(null);

    private static readonly string RepoRoot = FindRepoRoot();

    /// <summary>Services whose audience is carried in an environment variable.</summary>
    private static readonly string[] EnvConfiguredServices =
    {
        "ai-service", "budget-service", "chatbot-service",
        "account-opening-service", "banker-copilot-service"
    };

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "docker-compose.yml")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException("Could not locate the repository root.");
    }

    private static IDeserializer Yaml() => new DeserializerBuilder()
        .WithNamingConvention(NullNamingConvention.Instance)
        .IgnoreUnmatchedProperties()
        .Build();

    /// <summary>Environment as `docker compose` sees it, resolved from the list form.</summary>
    private static Dictionary<string, Dictionary<string, string>> ComposeEnvironment()
    {
        var text = File.ReadAllText(Path.Combine(RepoRoot, "docker-compose.yml"));
        var document = Yaml().Deserialize<Dictionary<string, object>>(text);
        var services = (Dictionary<object, object>)document["services"];

        var result = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);

        foreach (var (nameObject, definitionObject) in services)
        {
            var name = (string)nameObject;
            var environment = new Dictionary<string, string>(StringComparer.Ordinal);

            if (definitionObject is Dictionary<object, object> definition
                && definition.TryGetValue("environment", out var env)
                && env is List<object> entries)
            {
                foreach (var entry in entries.OfType<string>())
                {
                    var split = entry.IndexOf('=');
                    if (split > 0)
                    {
                        environment[entry[..split]] = entry[(split + 1)..];
                    }
                }
            }

            result[name] = environment;
        }

        return result;
    }

    private static Dictionary<string, Dictionary<string, string>> KustomizeEnvironment()
    {
        var result = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
        var directory = Path.Combine(RepoRoot, "deploy", "kustomize", "base");

        foreach (var path in Directory.EnumerateFiles(directory, "*.yaml"))
        {
            var text = File.ReadAllText(path);
            var environment = new Dictionary<string, string>(StringComparer.Ordinal);

            // Deliberately a light scan of `- name: X` / `value: "Y"` pairs rather than a full
            // manifest parse: the assertion is about the VALUES agreeing, and a parser that
            // silently returns nothing on a schema surprise would make this test vacuous.
            var lines = text.Split('\n');
            for (var i = 0; i < lines.Length - 1; i++)
            {
                var nameMatch = System.Text.RegularExpressions.Regex.Match(lines[i], @"^\s*- name: (\S+)\s*$");
                var valueMatch = System.Text.RegularExpressions.Regex.Match(lines[i + 1], @"^\s*value: ""?([^""\r]*)""?\s*$");
                if (nameMatch.Success && valueMatch.Success)
                {
                    environment[nameMatch.Groups[1].Value] = valueMatch.Groups[1].Value.Trim();
                }
            }

            result[Path.GetFileNameWithoutExtension(path)] = environment;
        }

        return result;
    }

    [Theory]
    [InlineData("docker-compose")]
    [InlineData("kustomize")]
    public void EveryEnvConfiguredService_DeclaresTheAudienceTheRegistryAssignsIt(string source)
    {
        var environments = source == "docker-compose" ? ComposeEnvironment() : KustomizeEnvironment();

        foreach (var service in EnvConfiguredServices)
        {
            var expected = Registry.AudienceFor(service);

            environments.Should().ContainKey(service, $"{source} must define {service}");
            environments[service].Should().ContainKey("JWT_AUDIENCE",
                $"{source}/{service} must state an audience — there is no default by design");

            environments[service]["JWT_AUDIENCE"].Should().Be(expected,
                $"{source}/{service} must agree with config/jwt-audiences.yaml, not restate it");
        }
    }

    [Theory]
    [InlineData("docker-compose")]
    [InlineData("kustomize")]
    public void OnlyMediatorTargets_DeclareTheMediatorAudience(string source)
    {
        var environments = source == "docker-compose" ? ComposeEnvironment() : KustomizeEnvironment();

        foreach (var service in EnvConfiguredServices)
        {
            if (!environments.TryGetValue(service, out var environment))
            {
                continue;
            }

            var declared = environment.GetValueOrDefault("JWT_ADDITIONAL_AUDIENCES", string.Empty)
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

            var shouldAccept = Registry.ValidAudiencesFor(service).Contains(Registry.MediatorAudience);

            declared.Contains(Registry.MediatorAudience).Should().Be(shouldAccept,
                $"{source}/{service}: whether it accepts the broker audience must be decided by " +
                "the registry's mediator.acceptedBy list, in one place");
        }
    }

    [Fact]
    public void NoDeploymentFileStillSetsARetiredSigningKey()
    {
        // The most important one. If any manifest still exports Jwt__Key or JWT_KEY, that
        // service now refuses to start — so this test failing is the difference between
        // finding out here and finding out in a CrashLoopBackOff.
        var offenders = new List<string>();

        var files = new List<string> { Path.Combine(RepoRoot, "docker-compose.yml") };
        files.AddRange(Directory.EnumerateFiles(Path.Combine(RepoRoot, "deploy", "kustomize", "base"), "*.yaml"));

        foreach (var path in files)
        {
            foreach (var line in File.ReadLines(path))
            {
                var trimmed = line.Trim();
                var isComment = trimmed.StartsWith('#');
                if (isComment)
                {
                    continue;
                }

                foreach (var retired in Registry.RetiredConfigKeys)
                {
                    if (trimmed.Contains($"{retired}=", StringComparison.Ordinal)
                        || trimmed.Contains($"name: {retired}", StringComparison.Ordinal))
                    {
                        offenders.Add($"{Path.GetFileName(path)}: {trimmed}");
                    }
                }
            }
        }

        offenders.Should().BeEmpty(
            "these settings are retired by #334 and every service fails closed when they are set");
    }

    [Fact]
    public void OnlyTheIssuerIsGivenAPrivateKey()
    {
        var offenders = new List<string>();

        foreach (var path in Directory.EnumerateFiles(Path.Combine(RepoRoot, "deploy", "kustomize", "base"), "*.yaml"))
        {
            var service = Path.GetFileNameWithoutExtension(path);
            var text = File.ReadAllText(path);

            var mentionsPrivateKey = text.Contains("Jwt__PrivateKeyPem", StringComparison.Ordinal)
                                     || text.Contains("JWT_PRIVATE_KEY_PEM", StringComparison.Ordinal);

            if (mentionsPrivateKey && !Registry.IsIssuer(service))
            {
                offenders.Add(service);
            }
        }

        offenders.Should().BeEmpty(
            "only user-service may hold signing material; everything else validates via JWKS");
    }

    [Fact]
    public void OnlyRegisteredMediatorClients_AreGivenTheBrokerCredential()
    {
        var offenders = new List<string>();

        foreach (var path in Directory.EnumerateFiles(Path.Combine(RepoRoot, "deploy", "kustomize", "base"), "*.yaml"))
        {
            var service = Path.GetFileNameWithoutExtension(path);
            var text = File.ReadAllText(path);

            if (!text.Contains("Jwt__MediatorClientSecret", StringComparison.Ordinal))
            {
                continue;
            }

            if (!Registry.IsMediatorClient(service))
            {
                offenders.Add(service);
            }
        }

        offenders.Should().BeEmpty(
            "the broker credential is what buys a mediator token; only authority-service may hold it");
    }
}
