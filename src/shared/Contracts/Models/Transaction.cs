using System;

namespace OnlineBankingDemo.Contracts.Models;

/// <summary>
/// Represents a financial transaction
/// </summary>
public class Transaction
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string AccountId { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Currency { get; set; } = "USD";
    public string Type { get; set; } = null!; // Deposit, Withdrawal, Transfer
    public string Status { get; set; } = "Pending"; // Pending, Completed, Failed
    public string Description { get; set; } = null!;
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    public string? RelatedTransactionId { get; set; } // For transfers
    public string Category { get; set; } = "Uncategorized";
}