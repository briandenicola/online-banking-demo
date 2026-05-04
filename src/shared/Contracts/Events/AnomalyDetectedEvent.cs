using System;

namespace OnlineBankingDemo.Contracts.Events;

/// <summary>
/// Event published when suspicious transaction is detected
/// </summary>
public class AnomalyDetectedEvent : IEvent
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string Source { get; set; } = "anomaly-service";
    public string TransactionId { get; set; } = null!;
    public string AccountId { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Reason { get; set; } = null!;
    public double ConfidenceScore { get; set; }
}