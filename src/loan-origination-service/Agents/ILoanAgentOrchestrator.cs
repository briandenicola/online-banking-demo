using LoanOrigination.Models;

namespace LoanOrigination.Agents;

/// <summary>
/// Interface for loan agent orchestrators (code-based and offline variants).
/// Runs S01-S10 workflow and returns a complete AgentRunResponse.
/// </summary>
public interface ILoanAgentOrchestrator
{
    Task<AgentRunResponse> RunWorkflowAsync(
        LoanApplication application,
        Action<string, string, string>? onStepUpdate = null);
    
    Task<bool> HealthCheckAsync();
}
