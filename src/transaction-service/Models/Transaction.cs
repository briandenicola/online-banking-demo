using System;
using System.Text.Json.Serialization;

namespace TransactionService.Models;

/// <summary>
/// Transaction model
/// </summary>
public class Transaction
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string AccountId { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Currency { get; set; } = "USD";
    public string Type { get; set; } = null!;
    public string Status { get; set; } = "Completed";
    public string Description { get; set; } = null!;
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string? RelatedTransactionId { get; set; }
    public string Category { get; set; } = "Uncategorized";
}