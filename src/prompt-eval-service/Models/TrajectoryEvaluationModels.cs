using Newtonsoft.Json;

namespace PromptEvalService.Models;

public enum TrajectoryScoreStatus
{
    Pass,
    Fail,
    Degraded
}

public class TrajectoryScoreResult
{
    [JsonProperty("scorerName")]
    public string ScorerName { get; set; } = string.Empty;

    [JsonProperty("status")]
    public TrajectoryScoreStatus Status { get; set; } = TrajectoryScoreStatus.Pass;

    [JsonProperty("details")]
    public Dictionary<string, object> Details { get; set; } = new();

    [JsonProperty("expected")]
    public Dictionary<string, object> Expected { get; set; } = new();

    [JsonProperty("actual")]
    public Dictionary<string, object> Actual { get; set; } = new();

    [JsonIgnore]
    public bool Passed => Status == TrajectoryScoreStatus.Pass;
}

public class TrajectoryEvaluationRecord
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    [JsonProperty("sessionId")]
    public string SessionId { get; set; } = "trajectory-eval";

    [JsonProperty("scenario")]
    public string Scenario { get; set; } = string.Empty;

    [JsonProperty("runId")]
    public string RunId { get; set; } = string.Empty;

    [JsonProperty("expectedEscalationRung")]
    public string? ExpectedEscalationRung { get; set; }

    [JsonProperty("predictedEscalationRung")]
    public string? PredictedEscalationRung { get; set; }

    [JsonProperty("results")]
    public List<TrajectoryScoreResult> Results { get; set; } = new();

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class EscalationConfusionMatrix
{
    [JsonProperty("labels")]
    public List<string> Labels { get; set; } = new() { "L1", "L2" };

    [JsonProperty("matrix")]
    public Dictionary<string, Dictionary<string, int>> Matrix { get; set; } = new();

    [JsonProperty("total")]
    public int Total { get; set; }

    [JsonProperty("correctPredictions")]
    public int CorrectPredictions { get; set; }
}
