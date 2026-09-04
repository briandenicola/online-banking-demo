using System.Net.Http.Headers;
using System.Text;
using AuthorityService.Models;
using Newtonsoft.Json;

namespace AuthorityService.Services;

public record BrokerResult(bool Succeeded, int? StatusCode, string? DownstreamRef, string? Error);

/// <summary>
/// Calls the downstream banking service that actually performs the approved action.
///
/// <para><b>Phase 1 limitation, stated plainly:</b> every service in this demo validates the
/// same symmetric JWT key against the same audience (issue #334), so there is no way to mint a
/// narrowly-scoped, single-use broker token that a downstream service would treat differently
/// from an ordinary user token. The broker therefore forwards the requester's own bearer token
/// and relies on the approval record for the authority trail. When #334 lands this becomes a
/// per-approval capability token — the seam is here, deliberately.</para>
///
/// <para>Base URLs come from configuration only. An unconfigured target fails closed rather
/// than guessing a hostname.</para>
/// </summary>
public interface IActionBroker
{
    Task<BrokerResult> ExecuteAsync(Approval approval, string? bearerToken, CancellationToken ct = default);
}

public class HttpActionBroker : IActionBroker
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _configuration;
    private readonly ILogger<HttpActionBroker> _logger;

    public HttpActionBroker(
        IHttpClientFactory httpClientFactory,
        IConfiguration configuration,
        ILogger<HttpActionBroker> logger)
    {
        _httpClientFactory = httpClientFactory;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<BrokerResult> ExecuteAsync(
        Approval approval, string? bearerToken, CancellationToken ct = default)
    {
        var service = approval.Target.Service;
        var baseUrl = _configuration[$"Downstream:{service}"];

        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            // Fail closed. A missing base URL is a deployment error, and silently defaulting to
            // a guessed hostname is how a demo action lands on a real service.
            return new BrokerResult(false, null,
                null, $"No base URL is configured for downstream service '{service}' " +
                      $"(expected Downstream__{service}).");
        }

        var url = baseUrl.TrimEnd('/') + approval.Target.ResolvedPath;

        using var request = new HttpRequestMessage(
            new HttpMethod(approval.Target.Method), url)
        {
            Content = new StringContent(
                approval.Payload.ToString(Formatting.None), Encoding.UTF8, "application/json")
        };

        if (!string.IsNullOrWhiteSpace(bearerToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
        }

        // Idempotency key = approval id. A retried execution of the same approval must not
        // produce a second effect downstream.
        request.Headers.TryAddWithoutValidation(
            "Idempotency-Key", approval.Execution.IdempotencyKey ?? approval.Id);
        request.Headers.TryAddWithoutValidation("X-Approval-Id", approval.Id);
        request.Headers.TryAddWithoutValidation("X-Approval-Payload-Hash", approval.PayloadHash);

        if (approval.CorrelationId is not null)
        {
            request.Headers.TryAddWithoutValidation("X-Correlation-ID", approval.CorrelationId);
        }

        try
        {
            var client = _httpClientFactory.CreateClient("downstream");
            using var response = await client.SendAsync(request, ct);
            var body = await response.Content.ReadAsStringAsync(ct);

            if (!response.IsSuccessStatusCode)
            {
                return new BrokerResult(false, (int)response.StatusCode, null,
                    $"Downstream {service} returned {(int)response.StatusCode}: {Truncate(body)}");
            }

            return new BrokerResult(true, (int)response.StatusCode, ExtractRef(body), null);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Broker call to {Service} failed for approval {ApprovalId}",
                service, approval.Id);

            return new BrokerResult(false, null, null, ex.Message);
        }
    }

    private static string? ExtractRef(string body)
    {
        try
        {
            var token = Newtonsoft.Json.Linq.JToken.Parse(body);

            if (token is Newtonsoft.Json.Linq.JObject obj)
            {
                foreach (var candidate in new[] { "id", "transactionId", "referenceId", "reference" })
                {
                    if (obj[candidate] is { } value && value.Type != Newtonsoft.Json.Linq.JTokenType.Null)
                    {
                        return value.ToString();
                    }
                }
            }
        }
        catch (JsonException)
        {
            // A non-JSON success body is fine; there is simply no reference to record.
        }

        return null;
    }

    private static string Truncate(string value) =>
        value.Length <= 500 ? value : value[..500] + "…";
}
