using AuthorityService.Models;
using AuthorityService.Policy;
using AuthorityService.Repositories;
using AuthorityService.Services;
using Newtonsoft.Json;

namespace AuthorityService.Middleware;

/// <summary>
/// Turns this service's refusals into stable, human-readable API errors.
///
/// Every refusal here is a designed one — a rule saying no. They are surfaced verbatim because
/// "403" tells a banker nothing, while "you requested this action, so you cannot also approve
/// it" tells them exactly what happened and why.
/// </summary>
public class AuthorityExceptionMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<AuthorityExceptionMiddleware> _logger;

    public AuthorityExceptionMiddleware(RequestDelegate next, ILogger<AuthorityExceptionMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (AuthorityException ex)
        {
            await WriteAsync(context, ex.StatusCode, ex.Code, ex.Message, ex.Data2);
        }
        catch (UnknownTerminalReasonException ex)
        {
            // Fail closed. An approval carrying a terminalReason outside the closed enum is not
            // served, not repaired, and not acted upon.
            _logger.LogError(ex, "Approval document carries an unrecognised terminalReason");

            await WriteAsync(context, 500, "corrupt_approval",
                "An approval record carries a terminal reason this service does not recognise. " +
                "Refusing to act on it.", new { offendingValue = ex.OffendingValue });
        }
        catch (ApprovalWriteGuardException ex)
        {
            _logger.LogWarning(ex, "Approval write rejected by the guard");

            await WriteAsync(context, 409, "invalid_transition", ex.Message);
        }
        catch (ApprovalConcurrencyException ex)
        {
            await WriteAsync(context, 409, "concurrent_modification", ex.Message);
        }
        catch (CanonicalizationException ex)
        {
            await WriteAsync(context, 400, "payload_not_canonicalizable", ex.Message);
        }
        catch (PolicyValidationException ex)
        {
            _logger.LogError(ex, "Policy validation failure while serving a request");

            await WriteAsync(context, 500, "policy_invalid", ex.Message);
        }
    }

    private static async Task WriteAsync(
        HttpContext context, int status, string code, string message, object? data = null)
    {
        if (context.Response.HasStarted) return;

        context.Response.Clear();
        context.Response.StatusCode = status;
        context.Response.ContentType = "application/json";

        var body = JsonConvert.SerializeObject(new
        {
            error = code,
            message,
            data,
            correlationId = context.TraceIdentifier
        });

        await context.Response.WriteAsync(body);
    }
}
