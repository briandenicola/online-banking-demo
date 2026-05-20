using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class DecisionRecord
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("runId")]
    public string RunId { get; set; } = string.Empty;

    [JsonProperty("reviewerId")]
    public string ReviewerId { get; set; } = string.Empty;

    [JsonProperty("reviewerName")]
    public string ReviewerName { get; set; } = string.Empty;

    [JsonProperty("decision")]
    public string Decision { get; set; } = string.Empty;

    [JsonProperty("adjustedAmount")]
    public decimal? AdjustedAmount { get; set; }

    [JsonProperty("adjustedTermMonths")]
    public int? AdjustedTermMonths { get; set; }

    [JsonProperty("adjustedRate")]
    public decimal? AdjustedRate { get; set; }

    [JsonProperty("notes")]
    public string Notes { get; set; } = string.Empty;

    [JsonProperty("recommendationSnapshot")]
    public UnderwritingRecommendation? RecommendationSnapshot { get; set; }

    [JsonProperty("fundingResult")]
    public FundingResult? FundingResult { get; set; }

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; }
}

public class FundingResult
{
    [JsonProperty("loanAccountId")]
    public string LoanAccountId { get; set; } = string.Empty;

    [JsonProperty("loanDisbursementId")]
    public string LoanDisbursementId { get; set; } = string.Empty;

    [JsonProperty("fundedAt")]
    public DateTime FundedAt { get; set; }
}
