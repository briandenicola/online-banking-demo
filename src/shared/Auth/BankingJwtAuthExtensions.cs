using System.Security.Cryptography;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;

namespace Banking.Auth;

/// <summary>
/// One registration path for JWT bearer authentication across every .NET service.
///
/// Before #334 each service configured its own <see cref="TokenValidationParameters"/>. Six
/// independent statements of the same policy is six places for it to drift, and the drift is
/// invisible because each file is internally coherent — the same failure mode that let a
/// privilege escalation live in the seam between two role models in Phase 1. Services now
/// state only their own NAME; everything else is derived.
/// </summary>
public static class BankingJwtAuthExtensions
{
    public static WebApplicationBuilder AddBankingJwtAuth(this WebApplicationBuilder builder, string serviceName)
    {
        var registry = JwtAudienceRegistry.Load(
            builder.Configuration[BankingJwtDefaults.RegistryPathConfigKey]
            ?? Environment.GetEnvironmentVariable("JWT_AUDIENCE_REGISTRY_PATH"));

        GuardRetiredConfiguration(builder.Configuration, registry, serviceName);
        GuardSigningMaterial(builder.Configuration, registry, serviceName);

        var validAudiences = registry.ValidAudiencesFor(serviceName);
        GuardMediatorAudience(registry, serviceName, validAudiences);

        builder.Services.AddSingleton(registry);

        var parameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidIssuer = builder.Configuration[BankingJwtDefaults.IssuerConfigKey] ?? registry.Issuer,
            ValidAudiences = validAudiences,

            // Pinning the algorithm is not belt-and-braces. Without it a validator that also
            // holds a symmetric key can be talked into HS256 by an attacker-supplied header —
            // the classic alg-confusion downgrade that turns the public key into a shared
            // secret and hands minting back to every holder.
            ValidAlgorithms = new[] { BankingJwtDefaults.Algorithm },
            RequireSignedTokens = true,
            RequireExpirationTime = true,
            ClockSkew = TimeSpan.FromSeconds(30)
        };

        ConfigureSigningKeys(builder, registry, serviceName, parameters);

        builder.Services.AddAuthentication(options =>
        {
            options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
            options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
        })
        .AddJwtBearer(options =>
        {
            options.UseSecurityTokenValidators = true;
            options.TokenValidationParameters = parameters;
        });

        return builder;
    }

    /// <summary>
    /// A retired security key that is merely ignored is worse than one that was never added:
    /// the operator who set <c>Jwt:Key</c> believes the platform is using it. Refuse to start.
    /// </summary>
    private static void GuardRetiredConfiguration(IConfiguration configuration, JwtAudienceRegistry registry, string serviceName)
    {
        var offenders = new List<string>();

        foreach (var key in registry.RetiredConfigKeys)
        {
            // `Jwt__Key` and `Jwt:Key` are the same setting to the .NET configuration binder;
            // check the raw environment too so an operator who exports the old variable is
            // told, rather than left believing symmetric signing is still in force.
            var configured = configuration[key.Replace("__", ":", StringComparison.Ordinal)];
            var fromEnvironment = Environment.GetEnvironmentVariable(key.Replace(":", "__", StringComparison.Ordinal));

            if (!string.IsNullOrWhiteSpace(configured) || !string.IsNullOrWhiteSpace(fromEnvironment))
            {
                offenders.Add(key);
            }
        }

        if (offenders.Count > 0)
        {
            throw new JwtConfigurationException(
                $"{serviceName}: the symmetric signing settings {string.Join(", ", offenders.Distinct())} " +
                "are retired (issue #334). Tokens are RS256 and only user-service holds a private " +
                "key. Remove these settings — leaving them set and ignored would misrepresent " +
                "the platform's security posture to whoever set them.");
        }
    }

    /// <summary>
    /// Structural containment: a service that is not the issuer refuses to run while holding
    /// signing material, whether or not it would ever have used it.
    ///
    /// This is what makes "banker-copilot-service cannot impersonate a signer" a property of
    /// the deployment rather than a property of the code being well-behaved. If a private key
    /// reaches the harness — mounted by mistake, inherited from a copied manifest, injected by
    /// a compromised secret store — the pod does not start.
    /// </summary>
    private static void GuardSigningMaterial(IConfiguration configuration, JwtAudienceRegistry registry, string serviceName)
    {
        if (registry.IsIssuer(serviceName))
        {
            return;
        }

        var privateKey = configuration[BankingJwtDefaults.PrivateKeyConfigKey]
                         ?? Environment.GetEnvironmentVariable("JWT_PRIVATE_KEY_PEM");

        if (!string.IsNullOrWhiteSpace(privateKey))
        {
            throw new JwtConfigurationException(
                $"{serviceName} was configured with JWT signing material, but only " +
                $"'{registry.IssuerService}' may mint tokens. A validation-key holder that can " +
                "also sign is exactly the property issue #334 exists to remove. Refusing to start.");
        }

        if (!registry.IsMediatorClient(serviceName)
            && !string.IsNullOrWhiteSpace(configuration[BankingJwtDefaults.MediatorClientSecretConfigKey]))
        {
            throw new JwtConfigurationException(
                $"{serviceName} was configured with a mediator client secret but is not listed " +
                "under 'mediator.clients' in config/jwt-audiences.yaml. Only the approval broker " +
                "may obtain a mediator token. Refusing to start.");
        }
    }

    /// <summary>
    /// Verified explicitly rather than assumed to follow from the registry. The property that
    /// makes the approval ladder real is that the mediator audience is not accepted at the
    /// mediator, so it is asserted here on the concrete audience list the handler will use.
    /// </summary>
    private static void GuardMediatorAudience(JwtAudienceRegistry registry, string serviceName, IReadOnlyList<string> validAudiences)
    {
        if (registry.RejectsMediatorAudience(serviceName)
            && validAudiences.Contains(registry.MediatorAudience, StringComparer.Ordinal))
        {
            throw new JwtConfigurationException(
                $"{serviceName} must reject the mediator audience '{registry.MediatorAudience}' " +
                "but its resolved audience list accepts it. A broker token replayed at the broker " +
                "would let an agent launder a downstream call through the approval path.");
        }

        if (validAudiences.Count == 0)
        {
            throw new JwtConfigurationException($"{serviceName} resolved an empty audience list.");
        }
    }

    private static void ConfigureSigningKeys(
        WebApplicationBuilder builder,
        JwtAudienceRegistry registry,
        string serviceName,
        TokenValidationParameters parameters)
    {
        // An explicitly supplied public key wins. This exists for tests and for an air-gapped
        // deployment that would rather pin the key than reach the issuer at runtime.
        var publicKeyPem = builder.Configuration[BankingJwtDefaults.PublicKeyConfigKey]
                           ?? Environment.GetEnvironmentVariable("JWT_PUBLIC_KEY_PEM");

        if (!string.IsNullOrWhiteSpace(publicKeyPem))
        {
            var rsa = JwtKeyMaterial.FromPublicPem(publicKeyPem!, BankingJwtDefaults.PublicKeyConfigKey);
            parameters.IssuerSigningKey = new RsaSecurityKey(rsa) { KeyId = JwtKeyMaterial.KeyId(rsa) };
            return;
        }

        // The issuer validates with its own public half — no network call, and no way for it to
        // be pointed at someone else's JWKS.
        if (registry.IsIssuer(serviceName))
        {
            var provider = new IssuerSigningKeyProvider(builder.Configuration);
            builder.Services.AddSingleton(provider);
            parameters.IssuerSigningKey = provider.PublicKey;
            return;
        }

        var jwksUri = builder.Configuration[BankingJwtDefaults.JwksUriConfigKey]
                      ?? Environment.GetEnvironmentVariable("JWT_JWKS_URI");

        if (string.IsNullOrWhiteSpace(jwksUri))
        {
            throw new JwtConfigurationException(
                $"{serviceName} has neither '{BankingJwtDefaults.PublicKeyConfigKey}' nor " +
                $"'{BankingJwtDefaults.JwksUriConfigKey}' configured. There is no default and no " +
                "fallback: a service that cannot obtain the issuer's public key must not accept " +
                "tokens.");
        }

        if (!Uri.TryCreate(jwksUri, UriKind.Absolute, out var uri))
        {
            throw new JwtConfigurationException($"{serviceName}: '{jwksUri}' is not an absolute URI.");
        }

        var resolver = new JwksSigningKeyResolver(
            uri,
            logger: LoggerFactory.Create(logging => logging.AddConsole()).CreateLogger<JwksSigningKeyResolver>());

        builder.Services.AddSingleton(resolver);
        parameters.IssuerSigningKeyResolver = resolver.Resolve;
    }
}

/// <summary>
/// Holds the issuer's private key. Registered ONLY in <c>user-service</c>.
///
/// Dual mode, fail closed: in cloud mode (<c>AZURE_CLIENT_ID</c> present) a private key must be
/// supplied, because an ephemeral per-replica key would mean two <c>user-service</c> pods sign
/// with different keys and half of every user's requests fail validation. Ephemeral generation
/// is a local-development affordance and is refused anywhere it could be mistaken for one.
/// </summary>
public sealed class IssuerSigningKeyProvider : IDisposable
{
    private readonly RSA _rsa;

    public string KeyId { get; }

    public RsaSecurityKey PrivateKey { get; }

    public RsaSecurityKey PublicKey { get; }

    public bool IsEphemeral { get; }

    public IssuerSigningKeyProvider(IConfiguration configuration)
    {
        var pem = configuration[BankingJwtDefaults.PrivateKeyConfigKey]
                  ?? Environment.GetEnvironmentVariable("JWT_PRIVATE_KEY_PEM");

        var entraMode = !string.IsNullOrWhiteSpace(configuration["AZURE_CLIENT_ID"])
                        || !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("AZURE_CLIENT_ID"));

        if (string.IsNullOrWhiteSpace(pem))
        {
            if (entraMode)
            {
                throw new JwtConfigurationException(
                    "AZURE_CLIENT_ID is set (cloud mode) but no JWT private key is configured. " +
                    "Refusing to fall back to an ephemeral key: with more than one replica each " +
                    "would sign with a different key, and a key that changes on restart cannot be " +
                    "revoked or audited. Supply Jwt:PrivateKeyPem from Key Vault.");
            }

            _rsa = JwtKeyMaterial.CreateEphemeral();
            IsEphemeral = true;
        }
        else
        {
            _rsa = JwtKeyMaterial.FromPrivatePem(pem!, BankingJwtDefaults.PrivateKeyConfigKey);
            IsEphemeral = false;
        }

        KeyId = JwtKeyMaterial.KeyId(_rsa);
        PrivateKey = new RsaSecurityKey(_rsa) { KeyId = KeyId };

        var publicOnly = RSA.Create();
        publicOnly.ImportParameters(_rsa.ExportParameters(includePrivateParameters: false));
        PublicKey = new RsaSecurityKey(publicOnly) { KeyId = KeyId };
    }

    public string JwksDocument() => JwksSigningKeyResolver.BuildJwksDocument(_rsa, KeyId);

    public void Dispose() => _rsa.Dispose();
}
