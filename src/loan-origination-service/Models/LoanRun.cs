using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class LoanRun
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("runId")]
    public string RunId { get; set; } = string.Empty;

    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("startedAt")]
    public DateTime StartedAt { get; set; }

    [JsonProperty("completedAt")]
    public DateTime? CompletedAt { get; set; }

    [JsonProperty("durationMs")]
    public long? DurationMs { get; set; }

    [JsonProperty("triggerKind")]
    public string TriggerKind { get; set; } = "run";

    [JsonProperty("prepared")]
    public PreparedData? Prepared { get; set; }

    [JsonProperty("workflowLog")]
    public List<WorkflowStep> WorkflowLog { get; set; } = new();

    [JsonProperty("recommendation")]
    public UnderwritingRecommendation? Recommendation { get; set; }

    [JsonProperty("errors")]
    public List<string> Errors { get; set; } = new();

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; }

    [JsonProperty("_etag")]
    public string? ETag { get; set; }
}

public class PreparedData
{
    [JsonProperty("creditProfile")]
    public CreditProfile? CreditProfile { get; set; }

    [JsonProperty("incomeVerification")]
    public IncomeVerification? IncomeVerification { get; set; }

    [JsonProperty("fraudSignals")]
    public FraudSignals? FraudSignals { get; set; }

    [JsonProperty("pricingQuote")]
    public ProductPricing? PricingQuote { get; set; }
}
