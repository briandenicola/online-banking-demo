using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class PolicyRule
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("ruleId")]
    public string RuleId { get; set; } = string.Empty;

    [JsonProperty("metric")]
    public string Metric { get; set; } = string.Empty;

    [JsonProperty("operator")]
    public string Operator { get; set; } = string.Empty;

    [JsonProperty("threshold")]
    public string Threshold { get; set; } = string.Empty;

    [JsonProperty("severity")]
    public string Severity { get; set; } = string.Empty;

    [JsonProperty("decisionEffect")]
    public string DecisionEffect { get; set; } = string.Empty;

    [JsonProperty("description")]
    public string Description { get; set; } = string.Empty;
}
