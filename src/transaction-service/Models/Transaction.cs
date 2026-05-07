using System;
using Newtonsoft.Json;

namespace TransactionService.Models;

/// <summary>
/// Transaction model
/// </summary>
public class Transaction
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    [JsonProperty("accountId")]
    public string AccountId { get; set; } = null!;

    [JsonProperty("userId")]
    public string? UserId { get; set; }

    [JsonProperty("amount")]
    public decimal Amount { get; set; }

    [JsonProperty("currency")]
    public string Currency { get; set; } = "USD";

    [JsonProperty("type")]
    public string Type { get; set; } = null!;

    [JsonProperty("status")]
    public string Status { get; set; } = "Completed";

    [JsonProperty("description")]
    public string Description { get; set; } = null!;

    [JsonProperty("timestamp")]
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;

    [JsonProperty("relatedTransactionId")]
    public string? RelatedTransactionId { get; set; }

    [JsonProperty("category")]
    public string Category { get; set; } = "Uncategorized";
}