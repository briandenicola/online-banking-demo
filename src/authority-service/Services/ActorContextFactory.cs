using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using AuthorityService.Policy;

namespace AuthorityService.Services;

/// <summary>
/// Turns an authenticated principal into the actor the evaluator sees.
///
/// Seniority is NOT read from the token — it is derived from the token's role claims via the
/// policy's <c>signerRoles</c> map. That keeps the ladder's notion of "senior enough" in the
/// policy file where it can be reviewed, instead of in a claim the token issuer controls.
/// </summary>
public class ActorContextFactory
{
    private static readonly string[] RoleClaimTypes =
    [
        ClaimTypes.Role, "role", "roles", "userRole"
    ];

    private readonly IPolicyProvider _policyProvider;

    public ActorContextFactory(IPolicyProvider policyProvider)
    {
        _policyProvider = policyProvider;
    }

    public ActorContext Create(ClaimsPrincipal principal, string? sessionId = null, bool selfDealing = false)
    {
        var userId = principal.FindFirstValue("userId")
                     ?? principal.FindFirstValue(ClaimTypes.NameIdentifier)
                     ?? principal.FindFirstValue(JwtRegisteredClaimNames.Sub)
                     ?? principal.Identity?.Name
                     ?? throw new AuthorityException("unauthenticated",
                         "The token carries no usable identity claim.", 401);

        var username = principal.FindFirstValue("username")
                       ?? principal.FindFirstValue(ClaimTypes.Name)
                       ?? principal.Identity?.Name;

        var roles = RoleClaimTypes
            .SelectMany(principal.FindAll)
            .Select(c => c.Value)
            .SelectMany(v => v.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        return new ActorContext
        {
            UserId = userId,
            Username = username,
            Role = roles.FirstOrDefault(),
            EffectiveRoles = roles,
            Seniority = _policyProvider.Current.SeniorityForRoles(roles),
            SessionId = sessionId,
            SelfDealing = selfDealing
        };
    }

    public static string TokenJti(ClaimsPrincipal principal) =>
        principal.FindFirstValue(JwtRegisteredClaimNames.Jti)
        ?? principal.FindFirstValue("jti")
        // A token with no jti still produces a signature; it just cannot be tied back to a
        // specific token instance. Recorded explicitly rather than silently blank.
        ?? "no-jti";
}
