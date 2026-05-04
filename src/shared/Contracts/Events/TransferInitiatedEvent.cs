using System;

namespace OnlineBankingDemo.Contracts.Events;

/// <summary>
/// Event published when a transfer is initiated
/// </summary>
public class TransferInitiatedEvent : IEvent
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string Source { get; set; } = "transfer-service";
    public string TransferId { get; set; } = null!;
    public string FromAccountId { get; set; } = null!;
    public string ToAccountId { get; set; } = null!;
    public decimal Amount { get; set; }
}