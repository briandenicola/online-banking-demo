using System;

namespace OnlineBankingDemo.Contracts.Models;

/// <summary>
/// Represents a bank account
/// </summary>
public class Account
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string UserId { get; set; } = null!;
    public string AccountNumber { get; set; } = null!;
    public string AccountType { get; set; } = null!; // Checking, Savings, etc.
    public decimal Balance { get; set; }
    public string Currency { get; set; } = "USD";
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public bool IsActive { get; set; } = true;
}