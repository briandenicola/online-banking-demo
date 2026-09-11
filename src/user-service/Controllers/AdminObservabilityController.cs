using Banking.Auth;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using UserService.Services;

namespace UserService.Controllers;

/// <summary>
/// Read-only observability under <c>/api/admin</c>, reachable by platform admins AND banking
/// supervisors.
///
/// <para>
/// This is a separate controller from <see cref="AdminController"/> on purpose, and the reason is
/// a property of ASP.NET Core rather than a matter of taste: authorization attributes on a
/// controller and on its actions are <b>ANDed</b>, never ORed. You cannot widen one action of an
/// admin-gated controller — you can only loosen the whole class and then narrow each action back.
/// Doing that on the controller that owns <c>promote</c>, <c>reset-password</c> and
/// <c>DELETE users/{id}</c> would make the permissive gate the DEFAULT there, so a future action
/// added without an attribute would silently inherit supervisor reachability. Absent-field-as-
/// permission is the failure this epic keeps paying for.
/// </para>
///
/// <para>
/// So <see cref="AdminController"/>'s blanket <c>[Authorize(Roles = admin)]</c> is left exactly as
/// it was, and the one read-only endpoint moved here instead. The split is structural: a mutating
/// endpoint cannot acquire the supervisor-readable gate without someone physically moving it into
/// a class called <c>Observability</c>. <c>SupervisorObservabilityScopeTests</c> asserts that no
/// one has.
/// </para>
///
/// <para>
/// The route is spelled <c>api/admin</c> explicitly (not <c>api/[controller]</c>) so the shipped
/// URL <c>/api/admin/login-audits</c> is unchanged by the move. This is a gate change, not an API
/// change.
/// </para>
///
/// <para>
/// The class gate is <see cref="BankingRoles.IdentityRead"/> — the <c>identity.read</c> capability
/// scope's ratified holders plus platform admin. Because controller and action attributes AND,
/// the class gate must be the UNION of what any action here needs, so it is only safe while every
/// action is a read of that scope. Both halves of that condition are asserted:
/// <c>SupervisorObservabilityScopeTests</c> fails on any non-GET action, and
/// <c>CapabilityScopeReadTests</c> fails if the banking half of the list drifts from
/// <c>config/authority-policy.yaml</c>.
/// </para>
///
/// <para>
/// Supervisors do NOT become admins. Epic #332 §5.8.2 is untouched: <c>admin</c> remains seniority
/// 0 implying nothing, and nothing in this file expands a role.
/// </para>
/// </summary>
[ApiController]
[Route("api/admin")]
[Authorize(Roles = BankingRoles.IdentityRead)]
public class AdminObservabilityController : ControllerBase
{
    private readonly IUserService _userService;

    public AdminObservabilityController(IUserService userService)
    {
        _userService = userService;
    }

    /// <summary>
    /// The Login Audit tab, and the copilot's <c>list_login_audits</c> evidence tool. Read-only:
    /// who signed in, from where, and whether it succeeded. A supervisor judging an L2 approval
    /// needs this background, and a banker's copilot needs it to gather the evidence
    /// <c>user.unlock</c> requires. It grants no ability to change an account, a role, or a policy.
    /// </summary>
    [HttpGet("login-audits")]
    public async Task<IActionResult> GetLoginAudits([FromQuery] int limit = 100)
    {
        if (limit <= 0 || limit > 1000)
            limit = 100;

        var audits = await _userService.GetLoginAuditsAsync(limit);
        return Ok(audits);
    }
}
