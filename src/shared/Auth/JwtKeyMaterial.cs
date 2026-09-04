using System.Security.Cryptography;
using Microsoft.IdentityModel.Tokens;

namespace Banking.Auth;

/// <summary>
/// Well-known configuration keys and claim names for the asymmetric token model.
/// Stated once so that a rename is a compile error rather than a service that quietly stops
/// reading the value an operator set.
/// </summary>
public static class BankingJwtDefaults
{
    /// <summary>The only signature algorithm this platform accepts.</summary>
    public const string Algorithm = SecurityAlgorithms.RsaSha256;

    public const string PrivateKeyConfigKey = "Jwt:PrivateKeyPem";
    public const string PublicKeyConfigKey = "Jwt:PublicKeyPem";
    public const string IssuerConfigKey = "Jwt:Issuer";
    public const string JwksUriConfigKey = "Jwt:JwksUri";
    public const string RegistryPathConfigKey = "Jwt:AudienceRegistryPath";
    public const string ExpiresInMinutesConfigKey = "Jwt:ExpiresInMinutes";
    public const string MediatorClientSecretConfigKey = "Jwt:MediatorClientSecret";

    /// <summary>Distinguishes a human session token from a broker (mediator) token.</summary>
    public const string TokenUseClaim = "token_use";

    public const string JwksPath = "/.well-known/jwks.json";
}

/// <summary>
/// RSA key material handling.
///
/// The asymmetry is the whole point of #334: under HS256 with a shared secret, the ability to
/// VERIFY a token was the ability to MINT one, so every one of the nine services was a
/// supervisor-token generator. With RS256 only <c>user-service</c> holds the private half.
/// </summary>
public static class JwtKeyMaterial
{
    /// <summary>Minimum modulus size. Below this a key is not a control, it is a formality.</summary>
    public const int MinimumKeySizeBits = 2048;

    public static RSA FromPrivatePem(string pem, string source)
    {
        var rsa = RSA.Create();
        try
        {
            rsa.ImportFromPem(pem.AsSpan());
        }
        catch (Exception exception)
        {
            rsa.Dispose();
            throw new JwtConfigurationException(
                $"{source} is not a readable PEM private key: {exception.Message}");
        }

        if (rsa.KeySize < MinimumKeySizeBits)
        {
            var size = rsa.KeySize;
            rsa.Dispose();
            throw new JwtConfigurationException(
                $"{source} is a {size}-bit RSA key; at least {MinimumKeySizeBits} bits are required.");
        }

        return rsa;
    }

    public static RSA FromPublicPem(string pem, string source)
    {
        var rsa = RSA.Create();
        try
        {
            rsa.ImportFromPem(pem.AsSpan());
        }
        catch (Exception exception)
        {
            rsa.Dispose();
            throw new JwtConfigurationException(
                $"{source} is not a readable PEM public key: {exception.Message}");
        }

        return rsa;
    }

    public static RSA CreateEphemeral() => RSA.Create(MinimumKeySizeBits);

    /// <summary>
    /// Stable key id derived from the public modulus, so the same key always advertises the
    /// same <c>kid</c> without anyone having to configure one.
    /// </summary>
    public static string KeyId(RSA rsa)
    {
        var parameters = rsa.ExportParameters(includePrivateParameters: false);
        var digest = SHA256.HashData(parameters.Modulus!);
        return Base64UrlEncoder.Encode(digest)[..16];
    }
}
