using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class AgentRunResponse
{
    [JsonProperty("runId")]
    public string RunId { get; set; } = string.Empty;

    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("startedAt")]
    public DateTime StartedAt { get; set; }

    [JsonProperty("completedAt")]
    public DateTime CompletedAt { get; set; }

    [JsonProperty("durationMs")]
    public long DurationMs { get; set; }

    [JsonProperty("workflowLog")]
    public List<WorkflowStep> WorkflowLog { get; set; } = new();

    [JsonProperty("recommendation")]
    public UnderwritingRecommendation Recommendation { get; set; } = new();

    [JsonProperty("errors")]
    public List<string> Errors { get; set; } = new();
}
