using System.Security.Cryptography;
using Microsoft.Extensions.Configuration;

namespace UserService.Tests;

/// <summary>
/// Builds configuration for tests that need to issue real tokens.
/// </summary>
/// <remarks>
/// After #334 the issuer runs in one of two modes and picks between them by
/// looking for <c>AZURE_CLIENT_ID</c> — including the ambient environment
/// variable, not just configuration. In cloud mode it refuses to invent an
/// ephemeral signing key, which is correct: a key that changes on restart cannot
/// be revoked or audited, and separate replicas would sign with different keys.
///
/// The consequence for tests is that they inherited the mode from whatever
/// machine ran them. With Azure credentials exported — which is to say, on the
/// machine of anyone who has recently deployed this repo — nine tests failed
/// with a configuration error before reaching a single assertion. On CI, with no
/// such variable, the very same tests passed. The suite was reporting a property
/// of the developer's shell.
///
/// Supplying a key here makes the tests state which mode they are exercising
/// instead of discovering it, and works under both. The key is generated per
/// run and never leaves the process: it is a test fixture, not a secret.
/// </remarks>
internal static class TestJwtConfiguration
{
    private static readonly Lazy<string> PrivateKeyPem = new(() =>
    {
        using var rsa = RSA.Create(2048);
        return rsa.ExportPkcs8PrivateKeyPem();
    });

    public static IConfiguration Build(IDictionary<string, string?>? overrides = null)
    {
        var settings = new Dictionary<string, string?>
        {
            ["Jwt:ExpiresInMinutes"] = "60",
            ["Jwt:PrivateKeyPem"] = PrivateKeyPem.Value
        };

        if (overrides is not null)
        {
            foreach (var (key, value) in overrides)
            {
                settings[key] = value;
            }
        }

        return new ConfigurationBuilder().AddInMemoryCollection(settings).Build();
    }
}
