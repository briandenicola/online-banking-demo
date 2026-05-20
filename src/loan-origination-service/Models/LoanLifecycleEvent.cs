using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class LoanLifecycleEvent
{
    [JsonProperty("event_type")]
    public string EventType { get; set; } = string.Empty;

    [JsonProperty("application_no")]
    public string? ApplicationNo { get; set; }

    [JsonProperty("run_id")]
    public string? RunId { get; set; }

    [JsonProperty("decision_id")]
    public string? DecisionId { get; set; }

    [JsonProperty("loan_account_id")]
    public string? LoanAccountId { get; set; }

    [JsonProperty("loan_disbursement_id")]
    public string? LoanDisbursementId { get; set; }

    [JsonProperty("user_id")]
    public string? UserId { get; set; }

    [JsonProperty("amount")]
    public decimal? Amount { get; set; }

    [JsonProperty("apr_pct")]
    public decimal? AprPct { get; set; }

    [JsonProperty("term_months")]
    public int? TermMonths { get; set; }

    [JsonProperty("loan_type")]
    public string? LoanType { get; set; }

    [JsonProperty("recommendation")]
    public string? Recommendation { get; set; }

    [JsonProperty("confidence")]
    public decimal? Confidence { get; set; }

    [JsonProperty("rationale")]
    public string? Rationale { get; set; }

    [JsonProperty("timestamp")]
    public DateTime Timestamp { get; set; }
}
