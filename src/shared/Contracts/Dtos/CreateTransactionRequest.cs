using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransactionRequest
{
    [Required]
    [StringLength(100)]
    public string AccountId { get; set; } = null!;

    [Required]
    [Range(-1000000, 1000000, ErrorMessage = "Amount must be between -1,000,000 and 1,000,000 and cannot be zero")]
    public decimal Amount { get; set; }

    [Required]
    [StringLength(50)]
    public string Type { get; set; } = null!;

    [Required]
    [StringLength(500)]
    public string Description { get; set; } = null!;

    [StringLength(10)]
    public string? Currency { get; set; }

    [StringLength(100)]
    public string? Category { get; set; }

    [StringLength(100)]
    public string? RelatedTransactionId { get; set; }

    public bool AutoCategorize { get; set; } = true;
}