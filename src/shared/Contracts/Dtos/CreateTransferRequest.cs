using System.ComponentModel.DataAnnotations;
using OnlineBankingDemo.Contracts.Validation;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransferRequest
{
    [Required]
    [StringLength(50, MinimumLength = 1)]
    public string FromAccountId { get; set; } = null!;

    [Required]
    [StringLength(50, MinimumLength = 1)]
    [NotEqualTo(nameof(FromAccountId),
        ErrorMessage = "ToAccountId must not equal FromAccountId (self-transfers are not allowed).")]
    public string ToAccountId { get; set; } = null!;

    [Required]
    [StringLength(50, MinimumLength = 1)]
    public string FromAccountNumber { get; set; } = null!;

    [Required]
    [StringLength(50, MinimumLength = 1)]
    public string ToAccountNumber { get; set; } = null!;

    [Required]
    [Range(0.01, 1000000, ErrorMessage = "Amount must be between 0.01 and 1,000,000")]
    public decimal Amount { get; set; }

    [StringLength(500)]
    public string? Description { get; set; }
}