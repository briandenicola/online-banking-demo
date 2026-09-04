using AuthorityService.Contracts;
using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace AuthorityService.Controllers;

[ApiController]
[Route("api/authority/approvals")]
[Authorize]
public class ApprovalsController : ControllerBase
{
    private readonly ApprovalService _approvals;
    private readonly ActorContextFactory _actors;
    private readonly ILogger<ApprovalsController> _logger;

    public ApprovalsController(
        ApprovalService approvals,
        ActorContextFactory actors,
        ILogger<ApprovalsController> logger)
    {
        _approvals = approvals;
        _actors = actors;
        _logger = logger;
    }

    /// <summary>The agent asks for permission. It never gets to act — only to ask.</summary>
    [HttpPost]
    public async Task<IActionResult> Propose([FromBody] ProposeRequest request, CancellationToken ct)
    {
        var actor = _actors.Create(HttpContext.User, request.SessionId);
        var approval = await _approvals.ProposeAsync(request, actor, CorrelationId(), ct);

        return CreatedAtAction(nameof(Get), new { id = approval.Id }, Project(approval, actor));
    }

    [HttpGet]
    public async Task<IActionResult> List(
        [FromQuery] string scope = "mine",
        [FromQuery] string? status = null,
        [FromQuery] string? sessionId = null,
        [FromQuery] string? actionId = null,
        [FromQuery] int limit = 25,
        CancellationToken ct = default)
    {
        var actor = _actors.Create(HttpContext.User, sessionId);

        var parsedScope = scope.ToLowerInvariant() switch
        {
            "mine" => ApprovalScope.Mine,
            "awaiting-me" or "awaiting_supervisor" => ApprovalScope.AwaitingSupervisor,
            "session" => ApprovalScope.Session,
            "all" => ApprovalScope.All,
            _ => throw new AuthorityException("invalid_scope",
                $"Unknown scope '{scope}'. Use mine, awaiting-me, session or all.", 400)
        };

        var query = new ApprovalQuery
        {
            Scope = parsedScope,
            RequesterId = parsedScope == ApprovalScope.Mine ? actor.UserId : null,
            // A supervisor never sees their own requests in the co-sign queue: they could not
            // sign them anyway, and showing them invites the attempt.
            ExcludeRequesterId = parsedScope == ApprovalScope.AwaitingSupervisor ? actor.UserId : null,
            SessionId = parsedScope == ApprovalScope.Session ? sessionId : null,
            Status = status is null ? null : ParseStatus(status),
            ActionId = actionId,
            Limit = Math.Clamp(limit, 1, 200)
        };

        var results = await _approvals.ListAsync(query, ct);

        return Ok(new
        {
            count = results.Count,
            items = results.Select(a => Project(a, actor)).ToList()
        });
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> Get(string id, CancellationToken ct)
    {
        var actor = _actors.Create(HttpContext.User);
        var approval = await _approvals.GetAsync(id, actor, ct);

        return Ok(Project(approval, actor));
    }

    [HttpPost("{id}/sign")]
    public async Task<IActionResult> Sign(string id, [FromBody] SignRequest request, CancellationToken ct)
    {
        var actor = _actors.Create(HttpContext.User);
        var jti = ActorContextFactory.TokenJti(HttpContext.User);

        var approval = await _approvals.SignAsync(id, actor, request ?? new SignRequest(), jti, ct);

        return Ok(Project(approval, actor));
    }

    [HttpPost("{id}/deny")]
    public async Task<IActionResult> Deny(string id, [FromBody] DenyRequest request, CancellationToken ct)
    {
        var actor = _actors.Create(HttpContext.User);
        var approval = await _approvals.DenyAsync(id, actor, request, ct);

        return Ok(Project(approval, actor));
    }

    /// <summary>
    /// Executes a signed approval. Passes through the §5.3.2 re-evaluation gate first — there is
    /// no other route from <c>signed</c> to <c>executed</c>.
    /// </summary>
    [HttpPost("{id}/execute")]
    public async Task<IActionResult> Execute(string id, CancellationToken ct)
    {
        var actor = _actors.Create(HttpContext.User);
        var bearer = HttpContext.Request.Headers.Authorization.ToString();

        if (bearer.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
        {
            bearer = bearer["Bearer ".Length..];
        }

        var result = await _approvals.ExecuteAsync(id, actor, bearer, ct);

        if (result.Voided)
        {
            // 409, not 200. The caller asked for an action that did not happen, and the
            // replacement is offered rather than assumed.
            return Conflict(new
            {
                error = "policy_rung_escalated",
                message = result.Approval.TerminalDetail,
                approval = Project(result.Approval, actor),
                replacement = result.Replacement is null ? null : Project(result.Replacement, actor)
            });
        }

        return Ok(Project(result.Approval, actor));
    }

    private ApprovalResponse Project(Approval approval, ActorContext actor)
    {
        var response = ApprovalResponse.From(approval);
        var (canSign, reason) = _approvals.EvaluateSignEligibility(approval, actor);

        response.CallerMaySign = canSign;
        response.CallerMaySignReason = reason;

        return response;
    }

    private static ApprovalStatus ParseStatus(string status) => status.ToLowerInvariant() switch
    {
        SharedIdentifiers.Status.Proposed => ApprovalStatus.Proposed,
        SharedIdentifiers.Status.Pending => ApprovalStatus.Pending,
        SharedIdentifiers.Status.Signed => ApprovalStatus.Signed,
        SharedIdentifiers.Status.Executed => ApprovalStatus.Executed,
        SharedIdentifiers.Status.Denied => ApprovalStatus.Denied,
        _ => throw new AuthorityException("invalid_status",
            $"Unknown status '{status}'. The lifecycle is " +
            $"{string.Join(", ", SharedIdentifiers.Status.All)} — there is no 'expired' or 'voided' " +
            "status; expiry is a denial carrying TTL_EXPIRED.", 400)
    };

    private string? CorrelationId() =>
        HttpContext.Request.Headers["X-Correlation-ID"].FirstOrDefault()
        ?? HttpContext.TraceIdentifier;
}
