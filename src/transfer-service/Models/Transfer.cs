using System;
using Newtonsoft.Json;

namespace TransferService.Models;

/// <summary>
/// Transfer model
/// </summary>
public class Transfer
{
    [JsonProperty("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string FromAccountId { get; set; } = null!;
    public string ToAccountId { get; set; } = null!;
    public string FromAccountNumber { get; set; } = null!;
    public string ToAccountNumber { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Currency { get; set; } = "USD";
    public string Status { get; set; } = "Pending";
    public DateTime InitiatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? CompletedAt { get; set; }
    public string? Description { get; set; }
    public string? FailureReason { get; set; }
}