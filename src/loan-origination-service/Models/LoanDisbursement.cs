using Newtonsoft.Json;

namespace LoanOrigination.Models;

public class LoanDisbursement
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    [JsonProperty("loanAccountId")]
    public string LoanAccountId { get; set; } = string.Empty;

    [JsonProperty("userId")]
    public string UserId { get; set; } = string.Empty;

    [JsonProperty("kind")]
    public string Kind { get; set; } = "funding";

    [JsonProperty("amount")]
    public decimal Amount { get; set; }

    [JsonProperty("currency")]
    public string Currency { get; set; } = "USD";

    [JsonProperty("occurredAt")]
    public DateTime OccurredAt { get; set; }

    [JsonProperty("memo")]
    public string Memo { get; set; } = string.Empty;

    [JsonProperty("metadata")]
    public Dictionary<string, string> Metadata { get; set; } = new();

    [JsonProperty("createdAt")]
    public DateTime CreatedAt { get; set; }
}
