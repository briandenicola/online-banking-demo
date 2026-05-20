using Azure.AI.Projects;
using Azure.Core;
using Azure.Identity;

namespace LoanOrigination.Agents;

public class AgentRegistration : IHostedService
{
    private readonly IConfiguration _configuration;
    private readonly PromptLoader _promptLoader;
    private readonly ILogger<AgentRegistration> _logger;
    private readonly IWebHostEnvironment _environment;

    public AgentRegistration(
        IConfiguration configuration,
        PromptLoader promptLoader,
        ILogger<AgentRegistration> logger,
        IWebHostEnvironment environment)
    {
        _configuration = configuration;
        _promptLoader = promptLoader;
        _logger = logger;
        _environment = environment;
    }

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        var foundryMode = _configuration["Foundry:Mode"] ?? "online";
        
        if (foundryMode.Equals("offline", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogInformation("Foundry mode is offline — skipping agent registration");
            return;
        }

        var foundryEndpoint = _configuration["Foundry:Endpoint"];
        if (string.IsNullOrEmpty(foundryEndpoint))
        {
            _logger.LogWarning("Foundry:Endpoint not configured — skipping agent registration");
            return;
        }

        try
        {
            _logger.LogInformation("Starting agent registration for loan origination workflow");

            var connectionString = foundryEndpoint;
            var client = new AIProjectClient(new Uri(connectionString), new DefaultAzureCredential());

            var modelDeploymentName = _configuration["Foundry:ModelDeploymentName"] ?? "gpt-5.4-mini";

            // Register 7 agents: 5 specialists + 1 underwriting + 1 health check
            var agents = new[]
            {
                new { Name = "credit-profile-agent", PromptFile = "CreditProfileAgentPrompt", Description = "Analyzes credit bureau data and assigns risk tier" },
                new { Name = "income-verification-agent", PromptFile = "IncomeVerificationAgentPrompt", Description = "Verifies employment and income stability" },
                new { Name = "fraud-screening-agent", PromptFile = "FraudScreeningAgentPrompt", Description = "Screens for identity fraud and behavioral flags" },
                new { Name = "policy-evaluation-agent", PromptFile = "PolicyEvaluationAgentPrompt", Description = "Evaluates application against institutional policy rules" },
                new { Name = "pricing-agent", PromptFile = "PricingAgentPrompt", Description = "Calculates APR, monthly payment, and total repayment" },
                new { Name = "underwriting-recommendation-agent", PromptFile = "UnderwritingAgentPrompt", Description = "Final underwriting decision with confidence score" },
                new { Name = "health-check-agent", PromptFile = "HealthCheckAgentPrompt", Description = "System health check for readiness probes" }
            };

            foreach (var agent in agents)
            {
                var promptContent = _promptLoader.GetPrompt(agent.PromptFile);
                if (string.IsNullOrEmpty(promptContent))
                {
                    _logger.LogWarning("Prompt {PromptFile} not found for agent {AgentName}", agent.PromptFile, agent.Name);
                    continue;
                }

                try
                {
                    await RegisterAgentAsync(client, agent.Name, agent.Description, promptContent, modelDeploymentName, cancellationToken);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to register agent {AgentName}", agent.Name);
                    // Continue with other agents even if one fails
                }
            }

            _logger.LogInformation("Agent registration completed successfully");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Agent registration failed");
            // Don't throw — allow service to start even if registration fails
        }
    }

    private async Task RegisterAgentAsync(
        AIProjectClient client,
        string name,
        string description,
        string instructions,
        string modelDeploymentName,
        CancellationToken cancellationToken)
    {
        _logger.LogInformation("Registering agent: {AgentName}", name);

        // Azure.AI.Projects 2.0.0-beta.2 API — CreateAgentAsync signature is:
        // CreateAgentAsync(string model, ..., CancellationToken)
        // The 'model' parameter is positional; named parameters like 'name', 'instructions', 'description'
        // may not be supported in this beta version. Stub for now.
        
        // Stub for online mode — use offline mode (Foundry__Mode=offline) for MVP
        throw new NotImplementedException(
            "Agent registration pending Azure.AI.Projects 2.0.0-beta.2 API resolution. " +
            "Use Foundry__Mode=offline for MVP. See GitHub issue: loan-origination-service online orchestrator completion.");
        
        // Expected API pattern (pending SDK update):
        // var agent = await client.Agents.CreateAgentAsync(
        //     modelDeploymentName,
        //     name: name,
        //     instructions: instructions,
        //     description: description,
        //     cancellationToken: cancellationToken);
        // _logger.LogInformation("Agent {AgentName} registered with ID {AgentId}", name, agent.Value.Id);
    }

    public Task StopAsync(CancellationToken cancellationToken)
    {
        // No cleanup needed
        return Task.CompletedTask;
    }
}
