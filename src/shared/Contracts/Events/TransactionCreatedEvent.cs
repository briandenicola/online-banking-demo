using System;

namespace OnlineBankingDemo.Contracts.Events;

/// <summary>
/// Event published when a transaction occurs
/// </summary>
public class TransactionCreatedEvent : IEvent
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string Source { get; set; } = "transaction-service";
    public string TransactionId { get; set; } = null!;
    public string AccountId { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Type { get; set; } = null!;
    public string Description { get; set; } = null!;
    public string Category { get; set; } = "Uncategorized";
}