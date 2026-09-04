using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Banking.Auth;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;
using UserService.Services;
using Xunit;

namespace Banking.Auth.Tests;

/// <summary>
/// The properties issue #334 exists to establish, each written so it fails loudly.
///
/// These are deliberately end-to-end at the token level rather than unit tests of the loader:
/// the defect being fixed was not that any single file was wrong, it was that nine internally
/// coherent files agreed on a model that turned every service into a token forger. So each
/// test mints a real token with the real issuer and validates it with the exact
/// <see cref="TokenValidationParameters"/> a named service builds at startup.
/// </summary>
public class TokenScopingTests
{
    private static readonly JwtAudienceRegistry Registry = JwtAudienceRegistry.Load(null);

    private static IConfiguration IssuerConfiguration(params (string Key, string Value)[] extra)
    {
        var settings = new Dictionary<string, string?>
        {
            ["Jwt:Issuer"] = Registry.Issuer,
            ["Jwt:ExpiresInMinutes"] = "60"
        };

        foreach (var (key, value) in extra)
        {
            settings[key] = value;
        }

        return new ConfigurationBuilder().AddInMemoryCollection(settings).Build();
    }

    private static (AuthService Service, IssuerSigningKeyProvider Keys) Issuer(
        params (string Key, string Value)[] extra)
    {
        var configuration = IssuerConfiguration(extra);
        var keys = new IssuerSigningKeyProvider(configuration);
        return (new AuthService(configuration, RoleHierarchy.Default, Registry, keys), keys);
    }

    /// <summary>
    /// The validation parameters the named service builds at startup, with the issuer's public
    /// key pinned. Mirrors <c>BankingJwtAuthExtensions</c>; kept minimal so a divergence there
    /// shows up as a failure here rather than as a green suite over a broken service.
    /// </summary>
    private static TokenValidationParameters ParametersFor(string service, SecurityKey publicKey) => new()
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = Registry.Issuer,
        ValidAudiences = Registry.ValidAudiencesFor(service),
        ValidAlgorithms = new[] { BankingJwtDefaults.Algorithm },
        RequireSignedTokens = true,
        IssuerSigningKey = publicKey,
        ClockSkew = TimeSpan.Zero
    };

    private static bool Accepts(string service, string token, SecurityKey publicKey)
    {
        try
        {
            new JwtSecurityTokenHandler().ValidateToken(token, ParametersFor(service, publicKey), out _);
            return true;
        }
        catch
        {
            return false;
        }
    }

    // ------------------------------------------------------------------------------------
    // 1. A token minted for service A is rejected by service B.
    // ------------------------------------------------------------------------------------

    [Fact]
    public async Task ScopedTokenForOneService_IsRejectedByEveryOtherService()
    {
        var (issuer, keys) = Issuer();

        var transferToken = await issuer.GenerateScopedTokenAsync(
            "user-1", "banker", "banker",
            Registry.SessionAudiences,
            new[] { Registry.AudienceFor("transfer-service") });

        Accepts("transfer-service", transferToken, keys.PublicKey)
            .Should().BeTrue("the token was minted for transfer-service");

        foreach (var service in Registry.Audiences.Keys.Where(s => s != "transfer-service"))
        {
            Accepts(service, transferToken, keys.PublicKey)
                .Should().BeFalse(
                    $"a token scoped to transfer-service must not be accepted by {service}; " +
                    "before #334 every service shared the audience 'banking-demo' and this " +
                    "token would have been a platform-wide bearer credential");
        }
    }

    /// <summary>
    /// The specific direction named in the issue, asserted explicitly rather than left to
    /// follow from the loop above: the approval broker must not accept a token minted for a
    /// money-movement service, and the money-movement service must not accept the broker's.
    /// </summary>
    [Fact]
    public async Task AuthorityAndTransferTokens_AreNotInterchangeable()
    {
        var (issuer, keys) = Issuer();

        var transferToken = await issuer.GenerateScopedTokenAsync(
            "user-1", "banker", "banker", Registry.SessionAudiences,
            new[] { Registry.AudienceFor("transfer-service") });

        var authorityToken = await issuer.GenerateScopedTokenAsync(
            "user-1", "banker", "banker", Registry.SessionAudiences,
            new[] { Registry.AudienceFor("authority-service") });

        Accepts("authority-service", transferToken, keys.PublicKey).Should().BeFalse();
        Accepts("transfer-service", authorityToken, keys.PublicKey).Should().BeFalse();
    }

    // ------------------------------------------------------------------------------------
    // 2. Holding a validation key confers no ability to mint.
    // ------------------------------------------------------------------------------------

    [Fact]
    public void PublicKeyHolder_CannotSignAnAcceptedToken()
    {
        var (_, keys) = Issuer();

        // Everything a consumer service has: the public half, exactly as JWKS publishes it.
        var publicOnly = RSA.Create();
        publicOnly.ImportParameters(
            ((RsaSecurityKey)keys.PublicKey).Rsa!.ExportParameters(includePrivateParameters: false));

        var attempt = () => new JwtSecurityTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Subject = new ClaimsIdentity(new[] { new Claim(ClaimTypes.Role, "supervisor") }),
            Expires = DateTime.UtcNow.AddMinutes(5),
            Issuer = Registry.Issuer,
            SigningCredentials = new SigningCredentials(
                new RsaSecurityKey(publicOnly), BankingJwtDefaults.Algorithm)
        });

        // Under the old HS256 model this is the line that would have SUCCEEDED, because the
        // validation secret and the signing secret were the same bytes.
        attempt.Should().Throw<Exception>(
            "a service holding only the public key must have nothing it can sign with");
    }

    [Fact]
    public void PublicKeyUsedAsAnHmacSecret_IsRejected()
    {
        var (_, keys) = Issuer();

        var publicPem = ((RsaSecurityKey)keys.PublicKey).Rsa!.ExportSubjectPublicKeyInfoPem();

        // The alg-confusion downgrade: sign HS256 using the *public key text* as the shared
        // secret and hope the validator infers the algorithm from the token header. Pinning
        // ValidAlgorithms is what stops this, and without it the public key would be a shared
        // secret again — handing minting back to every holder.
        var hmacKey = new SymmetricSecurityKey(
            SHA512.HashData(Encoding.UTF8.GetBytes(publicPem)));

        var forged = new JwtSecurityTokenHandler().WriteToken(
            new JwtSecurityTokenHandler().CreateToken(new SecurityTokenDescriptor
            {
                Subject = new ClaimsIdentity(new[]
                {
                    new Claim(JwtRegisteredClaimNames.Sub, "user-1"),
                    new Claim(ClaimTypes.Role, "supervisor"),
                    new Claim(JwtRegisteredClaimNames.Aud, Registry.AudienceFor("authority-service"))
                }),
                Expires = DateTime.UtcNow.AddMinutes(5),
                Issuer = Registry.Issuer,
                SigningCredentials = new SigningCredentials(hmacKey, SecurityAlgorithms.HmacSha512)
            }));

        Accepts("authority-service", forged, keys.PublicKey).Should().BeFalse();
    }

    // ------------------------------------------------------------------------------------
    // 3. A forged supervisor claim is rejected by authority-service.
    // ------------------------------------------------------------------------------------

    [Fact]
    public void ForgedSupervisorClaimFromAnotherKey_IsRejectedByAuthorityService()
    {
        var (_, keys) = Issuer();

        // Stand in for a compromised service that generates its own keypair and mints a token
        // claiming supervisor authority — the exact move that would satisfy an L2 co-signature.
        using var attackerKey = RSA.Create(2048);

        var forged = new JwtSecurityTokenHandler().WriteToken(
            new JwtSecurityTokenHandler().CreateToken(new SecurityTokenDescriptor
            {
                Subject = new ClaimsIdentity(new[]
                {
                    new Claim(JwtRegisteredClaimNames.Sub, "attacker"),
                    new Claim(ClaimTypes.Role, "supervisor"),
                    new Claim("effectiveRoles", "supervisor"),
                    new Claim(JwtRegisteredClaimNames.Aud, Registry.AudienceFor("authority-service"))
                }),
                Expires = DateTime.UtcNow.AddMinutes(5),
                Issuer = Registry.Issuer,
                SigningCredentials = new SigningCredentials(
                    new RsaSecurityKey(attackerKey), BankingJwtDefaults.Algorithm)
            }));

        Accepts("authority-service", forged, keys.PublicKey).Should().BeFalse(
            "only the issuer's key may mint; a supervisor claim is worth nothing without it");
    }

    // ------------------------------------------------------------------------------------
    // 4. The mediator audience — the property that makes the approval ladder load-bearing.
    // ------------------------------------------------------------------------------------

    [Fact]
    public void MediatorAudience_IsNotObtainableFromAnySessionToken()
    {
        Registry.SessionAudiences.Should().NotContain(Registry.MediatorAudience,
            "a token a human or a forwarding agent can hold must never be accepted as a broker token");
    }

    [Fact]
    public async Task MediatorToken_IsRejectedByTheMediatorItself()
    {
        var (issuer, keys) = Issuer(("Jwt:MediatorClients:authority-service", "test-broker-credential"));

        var brokerToken = await issuer.GenerateMediatorTokenAsync("authority-service", "test-broker-credential");

        Accepts("transfer-service", brokerToken, keys.PublicKey)
            .Should().BeTrue("authority-service executes approved actions against transfer-service");

        Accepts("authority-service", brokerToken, keys.PublicKey)
            .Should().BeFalse(
                "a broker token replayed at the broker would let an agent launder a downstream " +
                "call back through the approval path");

        Accepts("banker-copilot-service", brokerToken, keys.PublicKey)
            .Should().BeFalse("the harness must never accept or act on a broker token");
    }

    [Fact]
    public async Task MediatorToken_RequiresTheClientCredential()
    {
        var (issuer, _) = Issuer(("Jwt:MediatorClients:authority-service", "test-broker-credential"));

        var wrongSecret = async () =>
            await issuer.GenerateMediatorTokenAsync("authority-service", "not-the-credential");
        await wrongSecret.Should().ThrowAsync<UnauthorizedAccessException>();

        // The harness holds a banker's forwarded bearer token and nothing else. Even knowing
        // the client id, it is not a registered mediator client.
        var harness = async () =>
            await issuer.GenerateMediatorTokenAsync("banker-copilot-service", "test-broker-credential");
        await harness.Should().ThrowAsync<UnauthorizedAccessException>();
    }

    [Fact]
    public async Task MediatorEndpoint_RefusesToIssueAgainstAnUnsetCredential()
    {
        var (issuer, _) = Issuer();

        var act = async () => await issuer.GenerateMediatorTokenAsync("authority-service", "");
        await act.Should().ThrowAsync<JwtConfigurationException>(
            "an empty expected secret would make the endpoint open to anyone who can guess the client id");
    }

    // ------------------------------------------------------------------------------------
    // 5. Narrowing is monotonic.
    // ------------------------------------------------------------------------------------

    [Fact]
    public async Task ScopedToken_CannotBeTradedBackUp()
    {
        var (issuer, _) = Issuer();

        var held = new[] { Registry.AudienceFor("account-service") };

        var widen = async () => await issuer.GenerateScopedTokenAsync(
            "user-1", "banker", "banker", held,
            new[] { Registry.AudienceFor("transfer-service") });

        await widen.Should().ThrowAsync<JwtConfigurationException>();
    }

    [Fact]
    public async Task NarrowingCanNeverReachTheMediatorAudience()
    {
        var (issuer, _) = Issuer();

        var act = async () => await issuer.GenerateScopedTokenAsync(
            "user-1", "banker", "banker",
            Registry.SessionAudiences,
            new[] { Registry.MediatorAudience });

        await act.Should().ThrowAsync<JwtConfigurationException>(
            "the mediator audience is not in the session set, so it is never in the held set");
    }

    // ------------------------------------------------------------------------------------
    // 6. The ordinary path still works — test both directions or you have tested neither.
    // ------------------------------------------------------------------------------------

    [Fact]
    public async Task SessionToken_IsAcceptedByEveryServiceInTheSessionSet()
    {
        var (issuer, keys) = Issuer();

        var token = await issuer.GenerateTokenAsync("user-1", "banker", "banker");

        foreach (var service in Registry.Audiences.Keys)
        {
            Accepts(service, token, keys.PublicKey).Should().BeTrue(
                $"{service} is in the session audience set and a banker must be able to reach it");
        }
    }
}
