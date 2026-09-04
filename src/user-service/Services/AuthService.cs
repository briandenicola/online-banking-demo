using System;
using System.Collections.Generic;
using System.IdentityModel.Tokens.Jwt;
using System.Linq;
using System.Security.Claims;
using System.Threading.Tasks;
using Banking.Auth;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace UserService.Services;

/// <summary>
/// The platform's sole token issuer (issue #334).
///
/// Signing is RS256 and the private key lives here and nowhere else. Every other service holds
/// only the public half — fetched from <c>/.well-known/jwks.json</c> — so holding validation
/// material confers no ability to mint. Under the previous HS256 model the two were the same
/// capability, which meant any of the nine services (or anything that could read the shared
/// secret) could forge a token bearing any role, including <c>supervisor</c>.
/// </summary>
public class AuthService : IAuthService
{
    private readonly IConfiguration _configuration;
    private readonly IRoleHierarchy _roleHierarchy;
    private readonly JwtAudienceRegistry _registry;
    private readonly IssuerSigningKeyProvider _keyProvider;

    public AuthService(IConfiguration configuration)
        : this(configuration, RoleHierarchy.Default)
    {
    }

    public AuthService(IConfiguration configuration, IRoleHierarchy roleHierarchy)
        : this(
            configuration,
            roleHierarchy,
            JwtAudienceRegistry.Load(configuration[BankingJwtDefaults.RegistryPathConfigKey]
                                     ?? Environment.GetEnvironmentVariable("JWT_AUDIENCE_REGISTRY_PATH")),
            new IssuerSigningKeyProvider(configuration))
    {
    }

    public AuthService(
        IConfiguration configuration,
        IRoleHierarchy roleHierarchy,
        JwtAudienceRegistry registry,
        IssuerSigningKeyProvider keyProvider)
    {
        _configuration = configuration;
        _roleHierarchy = roleHierarchy;
        _registry = registry;
        _keyProvider = keyProvider;
    }

    public string KeyId => _keyProvider.KeyId;

    public string JwksDocument() => _keyProvider.JwksDocument();

    /// <summary>
    /// Mints a human session token. Its audience set is the registry's
    /// <c>session.audiences</c>, which deliberately excludes the mediator audience: no token a
    /// human can obtain — and therefore no token an agent can forward — is ever accepted as a
    /// broker token.
    /// </summary>
    public async Task<string> GenerateTokenAsync(string userId, string username, string role)
    {
        var claims = BuildUserClaims(userId, username, role);
        claims.Add(new Claim(BankingJwtDefaults.TokenUseClaim, _registry.SessionTokenUse));

        return await Task.FromResult(Write(claims, _registry.SessionAudiences, ExpiresInMinutes()));
    }

    /// <summary>
    /// Mints a token restricted to a subset of the audiences the caller already holds.
    ///
    /// Narrowing is monotonic — <see cref="JwtAudienceRegistry.Narrow"/> refuses any audience
    /// the presented token does not carry. That is what stops a scoped token from being traded
    /// back up, and it is why the mediator audience can never be reached this way: it is not in
    /// the session set, so it is never in the held set.
    /// </summary>
    public async Task<string> GenerateScopedTokenAsync(
        string userId,
        string username,
        string role,
        IEnumerable<string> heldAudiences,
        IEnumerable<string> requestedAudiences)
    {
        var narrowed = JwtAudienceRegistry.Narrow(heldAudiences, requestedAudiences);

        var claims = BuildUserClaims(userId, username, role);
        claims.Add(new Claim(BankingJwtDefaults.TokenUseClaim, _registry.SessionTokenUse));

        return await Task.FromResult(Write(claims, narrowed, ExpiresInMinutes()));
    }

    /// <summary>
    /// Mints a mediator (broker) token for a registered mediator client.
    ///
    /// The caller must prove it is that client with a credential configured only for it; a
    /// user's bearer token is deliberately NOT sufficient, because the harness forwards a
    /// user's bearer token and must not be able to obtain this. The result carries no user
    /// identity and no role claims, so it can authenticate a downstream execution but can never
    /// fill a signature slot.
    /// </summary>
    public async Task<string> GenerateMediatorTokenAsync(string clientId, string presentedSecret)
    {
        if (!_registry.IsMediatorClient(clientId))
        {
            throw new UnauthorizedAccessException($"'{clientId}' is not a registered mediator client.");
        }

        var expected = _configuration[$"Jwt:MediatorClients:{clientId}"];

        if (string.IsNullOrWhiteSpace(expected))
        {
            throw new JwtConfigurationException(
                $"No mediator client secret is configured for '{clientId}'. Refusing to issue a " +
                "broker token against an unset credential — an empty expected secret would make " +
                "the endpoint open to anyone who can guess the client id.");
        }

        if (!System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.UTF8.GetBytes(expected),
                System.Text.Encoding.UTF8.GetBytes(presentedSecret ?? string.Empty)))
        {
            throw new UnauthorizedAccessException("Mediator client credential rejected.");
        }

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, clientId),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new(BankingJwtDefaults.TokenUseClaim, _registry.MediatorTokenUse)
        };

        // Broker tokens are short-lived by construction: they exist for the duration of one
        // downstream execution, not for a human's working session.
        var minutes = int.Parse(
            _configuration["Jwt:MediatorExpiresInMinutes"] ?? "5",
            System.Globalization.CultureInfo.InvariantCulture);

        return await Task.FromResult(Write(claims, new[] { _registry.MediatorAudience }, minutes));
    }

    public async Task<bool> ValidateTokenAsync(string token)
    {
        var tokenHandler = new JwtSecurityTokenHandler();

        try
        {
            tokenHandler.ValidateToken(token, new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidateAudience = true,
                ValidateLifetime = true,
                ValidateIssuerSigningKey = true,
                ValidIssuer = _configuration[BankingJwtDefaults.IssuerConfigKey] ?? _registry.Issuer,
                ValidAudiences = _registry.ValidAudiencesFor(_registry.IssuerService),
                ValidAlgorithms = new[] { BankingJwtDefaults.Algorithm },
                RequireSignedTokens = true,
                IssuerSigningKey = _keyProvider.PublicKey,
                ClockSkew = TimeSpan.FromSeconds(30)
            }, out _);

            return await Task.FromResult(true);
        }
        catch
        {
            return await Task.FromResult(false);
        }
    }

    private int ExpiresInMinutes() => int.Parse(
        _configuration[BankingJwtDefaults.ExpiresInMinutesConfigKey]
        ?? throw new InvalidOperationException("Jwt:ExpiresInMinutes is not configured"),
        System.Globalization.CultureInfo.InvariantCulture);

    private List<Claim> BuildUserClaims(string userId, string username, string role)
    {
        // Expand the flat role ONCE, here, per epic #332 §5.8.2. The flat `role` claim is
        // retained unchanged for ADR-003 compatibility.
        var effectiveRoles = _roleHierarchy.Expand(role);

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, userId),
            new(JwtRegisteredClaimNames.UniqueName, username),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new("userId", userId),
            new(ClaimTypes.Role, role)
        };

        foreach (var effectiveRole in effectiveRoles)
        {
            claims.Add(new Claim(Constants.ClaimNames.EffectiveRoles, effectiveRole));

            // Also emit the implied roles as role claims so that existing
            // [Authorize(Roles = ...)] guards see the expansion without every controller in the
            // repo having to learn about effectiveRoles. The declared role is already present
            // above; skip the duplicate.
            if (!string.Equals(effectiveRole, role, StringComparison.OrdinalIgnoreCase))
            {
                claims.Add(new Claim(ClaimTypes.Role, effectiveRole));
            }
        }

        claims.Add(new Claim(
            Constants.ClaimNames.Seniority,
            _roleHierarchy.SeniorityOf(role).ToString(System.Globalization.CultureInfo.InvariantCulture)));

        return claims;
    }

    private string Write(IReadOnlyCollection<Claim> claims, IReadOnlyCollection<string> audiences, int expiresInMinutes)
    {
        var tokenHandler = new JwtSecurityTokenHandler();

        var identity = new ClaimsIdentity(claims);

        // SecurityTokenDescriptor.Audience is single-valued; the multi-audience form has to go
        // on as claims. Setting both would emit `aud` twice with different shapes.
        foreach (var audience in audiences)
        {
            identity.AddClaim(new Claim(JwtRegisteredClaimNames.Aud, audience));
        }

        var descriptor = new SecurityTokenDescriptor
        {
            Subject = identity,
            Expires = DateTime.UtcNow.AddMinutes(expiresInMinutes),
            Issuer = _configuration[BankingJwtDefaults.IssuerConfigKey] ?? _registry.Issuer,
            SigningCredentials = new SigningCredentials(_keyProvider.PrivateKey, BankingJwtDefaults.Algorithm)
        };

        var token = tokenHandler.CreateToken(descriptor);
        return tokenHandler.WriteToken(token);
    }

    /// <summary>Audiences carried by an already-issued token, for the narrowing exchange.</summary>
    public static IReadOnlyList<string> AudiencesOf(ClaimsPrincipal principal) =>
        principal.FindAll(JwtRegisteredClaimNames.Aud)
            .Concat(principal.FindAll("aud"))
            .Select(claim => claim.Value)
            .Distinct(StringComparer.Ordinal)
            .ToList();
}
