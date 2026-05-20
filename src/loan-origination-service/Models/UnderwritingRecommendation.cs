using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class UnderwritingRecommendation
{
    [JsonProperty("recommendation")]
    public string Recommendation { get; set; } = string.Empty;

    [JsonProperty("confidence")]
    public decimal Confidence { get; set; }

    [JsonProperty("rationale")]
    public string Rationale { get; set; } = string.Empty;

    [JsonProperty("riskFactors")]
    public List<string> RiskFactors { get; set; } = new();

    [JsonProperty("strengths")]
    public List<string> Strengths { get; set; } = new();

    [JsonProperty("conditions")]
    public List<string> Conditions { get; set; } = new();

    [JsonProperty("suggestedAmount")]
    public decimal? SuggestedAmount { get; set; }

    [JsonProperty("suggestedTermMonths")]
    public int? SuggestedTermMonths { get; set; }
}
