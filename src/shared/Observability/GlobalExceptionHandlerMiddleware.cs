using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Banking.Observability;

public class GlobalExceptionHandlerMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<GlobalExceptionHandlerMiddleware> _logger;
    private readonly bool _isDevelopment;

    public GlobalExceptionHandlerMiddleware(
        RequestDelegate next,
        ILogger<GlobalExceptionHandlerMiddleware> logger,
        IHostEnvironment environment)
    {
        _next = next;
        _logger = logger;
        _isDevelopment = environment.IsDevelopment();
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (Exception ex)
        {
            await HandleExceptionAsync(context, ex);
        }
    }

    private async Task HandleExceptionAsync(HttpContext context, Exception exception)
    {
        var (statusCode, error) = exception switch
        {
            ArgumentException or ArgumentNullException
                => (HttpStatusCode.BadRequest, "ValidationError"),

            UnauthorizedAccessException
                => (HttpStatusCode.Unauthorized, "Unauthorized"),

            InvalidOperationException
                => (HttpStatusCode.UnprocessableEntity, "OperationFailed"),

            KeyNotFoundException
                => (HttpStatusCode.NotFound, "NotFound"),

            OperationCanceledException
                => (HttpStatusCode.ServiceUnavailable, "RequestCancelled"),

            _
                => (HttpStatusCode.InternalServerError, "InternalError"),
        };

        var correlationId = context.Items["CorrelationId"]?.ToString();

        _logger.LogError(exception,
            "Unhandled exception {ErrorType} on {Method} {Path} [CorrelationId={CorrelationId}]",
            error, context.Request.Method, context.Request.Path, correlationId);

        context.Response.ContentType = "application/json";
        context.Response.StatusCode = (int)statusCode;

        var message = statusCode == HttpStatusCode.InternalServerError && !_isDevelopment
            ? "An unexpected error occurred. Please try again later."
            : exception.Message;

        var body = new
        {
            error,
            message,
            statusCode = (int)statusCode,
        };

        var json = JsonSerializer.Serialize(body, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        });

        await context.Response.WriteAsync(json);
    }
}
