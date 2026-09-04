using System.Collections.Generic;
using System.Threading.Tasks;

namespace UserService.Services;

public interface IAuthService
{
    /// <summary>Mints a human session token carrying the registry's session audience set.</summary>
    Task<string> GenerateTokenAsync(string userId, string username, string role);

    /// <summary>
    /// Mints a token restricted to a subset of <paramref name="heldAudiences"/>. Monotonic:
    /// requesting an audience the presented token does not carry is an error, never a widening.
    /// </summary>
    Task<string> GenerateScopedTokenAsync(
        string userId,
        string username,
        string role,
        IEnumerable<string> heldAudiences,
        IEnumerable<string> requestedAudiences);

    /// <summary>
    /// Mints a mediator (broker) token. Gated on a client credential, not on a user's bearer
    /// token, so a service that only ever sees forwarded user tokens cannot obtain one.
    /// </summary>
    Task<string> GenerateMediatorTokenAsync(string clientId, string presentedSecret);

    Task<bool> ValidateTokenAsync(string token);

    /// <summary>The issuer's public signing key, as a JWKS document body.</summary>
    string JwksDocument();
}