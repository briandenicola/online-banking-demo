using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;

namespace Banking.Auth;

/// <summary>
/// Resolves the issuer's public signing keys.
///
/// KEY DISTRIBUTION, BOTH MODES, ONE MECHANISM.
/// Every non-issuer service fetches the public half from <c>user-service</c>'s JWKS endpoint
/// instead of being configured with a copy. That means:
///
///   * <b>Local (docker-compose):</b> nothing has to be generated, mounted or committed.
///     `user-service` creates an ephemeral keypair at startup when no private key is
///     configured, and every other container discovers the public half over the compose
///     network. No private key is ever baked into an image and none is ever committed.
///   * <b>Cloud (AKS):</b> `user-service` loads a stable private key from Key Vault through
///     the existing CSI secret provider. Consumers are unchanged — they still fetch JWKS —
///     so rotating the key requires touching exactly one secret and no consumer config.
///
/// Fetching is lazy and cached rather than done at startup on purpose: doing it at startup
/// would make every service depend on `user-service` being up first, which docker-compose
/// does not guarantee and which would turn a slow issuer boot into a cluster-wide crashloop.
/// A failure to fetch fails the request closed (no key, no validation), never open.
/// </summary>
public sealed class JwksSigningKeyResolver
{
    private readonly Uri _jwksUri;
    private readonly HttpClient _httpClient;
    private readonly ILogger? _logger;
    private readonly TimeSpan _cacheLifetime;
    private readonly SemaphoreSlim _refreshLock = new(1, 1);

    private IReadOnlyCollection<SecurityKey> _cached = Array.Empty<SecurityKey>();
    private DateTimeOffset _cachedAtUtc = DateTimeOffset.MinValue;

    public JwksSigningKeyResolver(
        Uri jwksUri,
        HttpClient? httpClient = null,
        ILogger? logger = null,
        TimeSpan? cacheLifetime = null)
    {
        _jwksUri = jwksUri;
        _httpClient = httpClient ?? new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        _logger = logger;
        _cacheLifetime = cacheLifetime ?? TimeSpan.FromMinutes(10);
    }

    /// <summary>
    /// <see cref="TokenValidationParameters.IssuerSigningKeyResolver"/> shape. Returns every
    /// candidate key; the handler picks by <c>kid</c>. On a miss we force a refresh once so a
    /// key rotation does not require a restart of eleven services.
    /// </summary>
    public IEnumerable<SecurityKey> Resolve(string token, SecurityToken securityToken, string? kid, TokenValidationParameters parameters)
    {
        var keys = GetKeys(forceRefresh: false);

        if (!string.IsNullOrEmpty(kid) && !keys.Any(key => string.Equals(key.KeyId, kid, StringComparison.Ordinal)))
        {
            keys = GetKeys(forceRefresh: true);
        }

        return keys;
    }

    private IReadOnlyCollection<SecurityKey> GetKeys(bool forceRefresh)
    {
        var fresh = DateTimeOffset.UtcNow - _cachedAtUtc < _cacheLifetime;
        if (!forceRefresh && fresh && _cached.Count > 0)
        {
            return _cached;
        }

        _refreshLock.Wait();
        try
        {
            fresh = DateTimeOffset.UtcNow - _cachedAtUtc < _cacheLifetime;
            if (!forceRefresh && fresh && _cached.Count > 0)
            {
                return _cached;
            }

            var payload = _httpClient.GetStringAsync(_jwksUri).GetAwaiter().GetResult();
            var keySet = new JsonWebKeySet(payload);
            var keys = keySet.GetSigningKeys().ToList();

            if (keys.Count == 0)
            {
                _logger?.LogError("JWKS at {JwksUri} advertised no signing keys", _jwksUri);
                return _cached;
            }

            _cached = keys;
            _cachedAtUtc = DateTimeOffset.UtcNow;
            _logger?.LogInformation("Loaded {Count} signing key(s) from {JwksUri}", keys.Count, _jwksUri);
            return _cached;
        }
        catch (Exception exception)
        {
            // Deliberately does NOT throw: returning the (possibly empty) cache makes
            // validation fail closed with a 401 rather than a 500, and keeps a transient
            // issuer outage from taking every consumer down with it.
            _logger?.LogError(exception, "Failed to fetch JWKS from {JwksUri}", _jwksUri);
            return _cached;
        }
        finally
        {
            _refreshLock.Release();
        }
    }

    /// <summary>Serialises an RSA public key into a JWKS document body.</summary>
    public static string BuildJwksDocument(System.Security.Cryptography.RSA rsa, string keyId)
    {
        var parameters = rsa.ExportParameters(includePrivateParameters: false);

        var document = new
        {
            keys = new[]
            {
                new
                {
                    kty = "RSA",
                    use = "sig",
                    alg = "RS256",
                    kid = keyId,
                    n = Base64UrlEncoder.Encode(parameters.Modulus!),
                    e = Base64UrlEncoder.Encode(parameters.Exponent!)
                }
            }
        };

        return JsonSerializer.Serialize(document);
    }
}
