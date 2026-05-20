using Microsoft.AspNetCore.Mvc;
using Microsoft.Azure.Cosmos;

namespace LoanOrigination.Controllers;

[ApiController]
[Route("[controller]")]
public class HealthController : ControllerBase
{
    private readonly CosmosClient _cosmosClient;
    private readonly IConfiguration _configuration;
    private readonly ILogger<HealthController> _logger;

    public HealthController(
        CosmosClient cosmosClient,
        IConfiguration configuration,
        ILogger<HealthController> logger)
    {
        _cosmosClient = cosmosClient;
        _configuration = configuration;
        _logger = logger;
    }

    [HttpGet("healthz")]
    public IActionResult Healthz()
    {
        return Ok(new
        {
            status = "healthy",
            service = "loan-origination-service",
            timestamp = DateTime.UtcNow
        });
    }

    [HttpGet("readyz")]
    public async Task<IActionResult> Readyz()
    {
        try
        {
            // Probe Cosmos connectivity
            var databaseName = _configuration["CosmosDb:DatabaseName"] ?? "BankingDemo";
            var database = _cosmosClient.GetDatabase(databaseName);
            var container = database.GetContainer("loan-policy");
            
            // Lightweight query to verify connectivity
            var query = "SELECT TOP 1 c.id FROM c";
            var iterator = container.GetItemQueryIterator<dynamic>(query);
            if (iterator.HasMoreResults)
            {
                await iterator.ReadNextAsync();
            }

            // Check Foundry mode
            var foundryMode = _configuration["Foundry:Mode"] ?? "online";
            var foundryStatus = foundryMode.Equals("offline", StringComparison.OrdinalIgnoreCase)
                ? "offline (expected)"
                : "online";

            return Ok(new
            {
                status = "ready",
                cosmos = "healthy",
                foundry = foundryStatus,
                timestamp = DateTime.UtcNow
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Readiness check failed");
            return StatusCode(503, new
            {
                status = "not ready",
                error = ex.Message,
                timestamp = DateTime.UtcNow
            });
        }
    }
}
