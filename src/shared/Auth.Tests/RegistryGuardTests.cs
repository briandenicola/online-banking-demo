using Banking.Auth;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace Banking.Auth.Tests;

/// <summary>
/// Fail-closed startup behaviour.
///
/// Every assertion here is about REFUSING TO RUN. A silently-ignored security toggle is worse
/// than one that was never added: the operator who set <c>Jwt:Key</c> believes symmetric
/// signing is in force, and nothing tells them otherwise. Likewise a non-issuer that finds a
/// private key in its environment has to stop, not shrug — that is what turns "the harness
/// cannot impersonate a signer" from a property of well-behaved code into a property of the
/// deployment.
/// </summary>
public class RegistryGuardTests
{
    private const string ValidRegistry = """
        version: 1
        issuer:
          name: user-service
          service: user-service
        audiences:
          user-service: banking-demo/user
          authority-service: banking-demo/authority
          transfer-service: banking-demo/transfer
          banker-copilot-service: banking-demo/copilot
        session:
          audiences:
            - banking-demo/user
            - banking-demo/authority
            - banking-demo/transfer
            - banking-demo/copilot
          tokenUse: session
        mediator:
          audience: banking-demo/mediator
          tokenUse: mediator
          clients:
            - authority-service
          acceptedBy:
            - transfer-service
          rejectedBy:
            - authority-service
            - banker-copilot-service
            - user-service
        retiredConfigKeys:
          - Jwt:Key
        """;

    [Fact]
    public void ValidRegistry_Parses()
    {
        var registry = JwtAudienceRegistry.Parse(ValidRegistry);

        registry.AudienceFor("transfer-service").Should().Be("banking-demo/transfer");
        registry.ValidAudiencesFor("transfer-service").Should().Contain("banking-demo/mediator");
        registry.ValidAudiencesFor("authority-service").Should().NotContain("banking-demo/mediator");
        registry.IsMediatorClient("authority-service").Should().BeTrue();
        registry.IsMediatorClient("banker-copilot-service").Should().BeFalse();
    }

    [Fact]
    public void MediatorAudienceInSessionSet_IsRejected()
    {
        var broken = ValidRegistry.Replace(
            "    - banking-demo/copilot",
            "    - banking-demo/copilot\n    - banking-demo/mediator");

        var act = () => JwtAudienceRegistry.Parse(broken);

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*session.audiences*");
    }

    [Fact]
    public void TwoServicesSharingAnAudience_IsRejected()
    {
        // The pre-#334 state, expressed in the new file format. It must not be expressible
        // silently: a shared audience is a platform-wide bearer token by another name.
        var broken = ValidRegistry.Replace(
            "  transfer-service: banking-demo/transfer",
            "  transfer-service: banking-demo/authority");

        var act = () => JwtAudienceRegistry.Parse(broken);

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*unique per service*");
    }

    [Fact]
    public void AuthorityServiceMissingFromRejectedBy_IsRejected()
    {
        var broken = ValidRegistry.Replace("    - authority-service\n    - banker-copilot-service",
                                           "    - banker-copilot-service");

        var act = () => JwtAudienceRegistry.Parse(broken);

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*mediator.rejectedBy*");
    }

    [Fact]
    public void HarnessAsMediatorClient_IsRejected()
    {
        var broken = ValidRegistry.Replace(
            "  clients:\n    - authority-service",
            "  clients:\n    - authority-service\n    - banker-copilot-service");

        var act = () => JwtAudienceRegistry.Parse(broken);

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*banker-copilot-service*never*");
    }

    [Fact]
    public void UnknownService_IsFatalRatherThanDefaulted()
    {
        var registry = JwtAudienceRegistry.Parse(ValidRegistry);

        var act = () => registry.AudienceFor("some-new-service");

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*no entry in the JWT audience registry*");
    }

    [Fact]
    public void Narrowing_RefusesAnyAudienceNotAlreadyHeld()
    {
        var act = () => JwtAudienceRegistry.Narrow(
            new[] { "banking-demo/account" },
            new[] { "banking-demo/account", "banking-demo/transfer" });

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*narrows only*");
    }

    [Fact]
    public void Narrowing_ToASubsetSucceeds()
    {
        var result = JwtAudienceRegistry.Narrow(
            new[] { "banking-demo/account", "banking-demo/transfer" },
            new[] { "banking-demo/account" });

        result.Should().ContainSingle().Which.Should().Be("banking-demo/account");
    }

    [Fact]
    public void EmptyNarrowing_IsRejected()
    {
        var act = () => JwtAudienceRegistry.Narrow(new[] { "banking-demo/account" }, Array.Empty<string>());

        act.Should().Throw<JwtConfigurationException>();
    }

    /// <summary>
    /// The repository's real registry, not a fixture. Guards against someone adding a service
    /// to the file in a way the loader would reject at every pod's startup instead of here.
    /// </summary>
    [Fact]
    public void TheRepositoryRegistry_Loads()
    {
        var registry = JwtAudienceRegistry.Load(null);

        registry.Issuer.Should().Be("user-service");
        registry.RejectsMediatorAudience("authority-service").Should().BeTrue();
        registry.RejectsMediatorAudience("banker-copilot-service").Should().BeTrue();
        registry.IsMediatorClient("banker-copilot-service").Should().BeFalse();
        registry.RetiredConfigKeys.Should().Contain("JWT_KEY");
    }

    [Fact]
    public void EmbeddedRegistry_MatchesTheFileOnDisk()
    {
        // Containers load the embedded copy; `dotnet test` loads the file. If the two could
        // diverge, everything verified here would be verifying something no pod runs.
        using var stream = typeof(JwtAudienceRegistry).Assembly
            .GetManifestResourceStream(JwtAudienceRegistry.EmbeddedResourceName);

        stream.Should().NotBeNull("Auth.csproj embeds config/jwt-audiences.yaml");

        using var reader = new StreamReader(stream!);
        var embedded = JwtAudienceRegistry.Parse(reader.ReadToEnd(), "embedded");
        var onDisk = JwtAudienceRegistry.Load(null);

        embedded.Audiences.Should().BeEquivalentTo(onDisk.Audiences);
        embedded.MediatorAudience.Should().Be(onDisk.MediatorAudience);
        embedded.SessionAudiences.Should().BeEquivalentTo(onDisk.SessionAudiences);
    }

    [Fact]
    public void IssuerInCloudModeWithoutAKey_RefusesToStart()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["AZURE_CLIENT_ID"] = "00000000-0000-0000-0000-000000000000"
            })
            .Build();

        var act = () => new IssuerSigningKeyProvider(configuration);

        act.Should().Throw<JwtConfigurationException>()
            .WithMessage("*ephemeral*",
                "two replicas signing with different keys would fail half of every user's requests");
    }

    [Fact]
    public void IssuerInLocalMode_GeneratesAnEphemeralKey()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>())
            .Build();

        using var provider = new IssuerSigningKeyProvider(configuration);

        provider.IsEphemeral.Should().BeTrue("docker compose up must work with no key material");
        provider.JwksDocument().Should().Contain("\"kty\":\"RSA\"").And.NotContain("\"d\"",
            "a JWKS document must never carry a private exponent");
    }
}
