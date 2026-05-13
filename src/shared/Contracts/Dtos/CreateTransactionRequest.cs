using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using OnlineBankingDemo.Contracts.Validation;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransactionRequest
{
    [Required]
    [StringLength(100, MinimumLength = 1)]
    public string AccountId { get; set; } = null!;

    [Required]
    [Range(-1000000, 1000000, ErrorMessage = "Amount must be between -1,000,000 and 1,000,000.")]
    [NotZero(ErrorMessage = "Amount must not be zero.")]
    public decimal Amount { get; set; }

    [Required]
    [StringLength(50)]
    [RegularExpression("^(Debit|Credit|Transfer|Deposit|Withdrawal)$",
        ErrorMessage = "Type must be one of: Debit, Credit, Transfer, Deposit, Withdrawal.")]
    public string Type { get; set; } = null!;

    [Required]
    [StringLength(500, MinimumLength = 1)]
    public string Description { get; set; } = null!;

    [StringLength(3, MinimumLength = 3)]
    [RegularExpression("^[A-Z]{3}$", ErrorMessage = "Currency must be an ISO 4217 3-letter code (e.g. USD).")]
    public string? Currency { get; set; }

    [StringLength(100)]
    public string? Category { get; set; }

    [StringLength(100)]
    public string? RelatedTransactionId { get; set; }

    public bool AutoCategorize { get; set; } = true;
}