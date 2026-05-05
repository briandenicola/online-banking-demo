using System;
using System.Collections.Generic;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransactionRequest
{
    public string AccountId { get; set; } = null!;
    public decimal Amount { get; set; }
    public string Type { get; set; } = null!;
    public string Description { get; set; } = null!;
    public string? Currency { get; set; }
    public string? Category { get; set; }
    public string? RelatedTransactionId { get; set; }
    public bool AutoCategorize { get; set; } = true; // New flag to trigger AI categorization
}