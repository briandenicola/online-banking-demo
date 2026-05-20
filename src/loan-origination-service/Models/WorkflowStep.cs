using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class WorkflowStep
{
    [JsonProperty("stepId")]
    public string StepId { get; set; } = string.Empty;

    [JsonProperty("stepName")]
    public string StepName { get; set; } = string.Empty;

    [JsonProperty("status")]
    public string Status { get; set; } = "pending";

    [JsonProperty("timestamp")]
    public DateTime Timestamp { get; set; }

    [JsonProperty("agentName")]
    public string? AgentName { get; set; }

    [JsonProperty("detail")]
    public string Detail { get; set; } = string.Empty;
}
