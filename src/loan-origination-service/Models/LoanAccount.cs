using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class LoanAccount
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("userId")]
    public string UserId { get; set; } = string.Empty;

    [JsonProperty("applicationNo")]
    public string ApplicationNo { get; set; } = string.Empty;

    [JsonProperty("decisionId")]
    public string DecisionId { get; set; } = string.Empty;

    [JsonProperty("loanType")]
    public string LoanType { get; set; } = string.Empty;

    [JsonProperty("principalBalance")]
    public decimal PrincipalBalance { get; set; }

    [JsonProperty("originalPrincipal")]
    public decimal OriginalPrincipal { get; set; }

    [JsonProperty("aprPct")]
    public decimal AprPct { get; set; }

    [JsonProperty("termMonths")]
    public int TermMonths { get; set; }

    [JsonProperty("monthlyPayment")]
    public decimal MonthlyPayment { get; set; }

    [JsonProperty("totalRepayableAmount")]
    public decimal TotalRepayableAmount { get; set; }

    [JsonProperty("originationDate")]
    public DateTime OriginationDate { get; set; }

    [JsonProperty("firstPaymentDate")]
    public string FirstPaymentDate { get; set; } = string.Empty;

    [JsonProperty("payoffDate")]
    public string PayoffDate { get; set; } = string.Empty;

    [JsonProperty("status")]
    public string Status { get; set; } = "funded";

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; }

    [JsonProperty("updatedAt")]
    public DateTime UpdatedAt { get; set; }

    [JsonProperty("_etag")]
    public string? ETag { get; set; }
}
