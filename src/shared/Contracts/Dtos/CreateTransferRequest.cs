using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransferRequest
{
    [Required]
    [StringLength(50)]
    public string FromAccountId { get; set; } = null!;

    [Required]
    [StringLength(50)]
    public string ToAccountId { get; set; } = null!;

    [Required]
    [StringLength(50)]
    public string FromAccountNumber { get; set; } = null!;

    [Required]
    [StringLength(50)]
    public string ToAccountNumber { get; set; } = null!;

    [Required]
    [Range(0.01, 1000000, ErrorMessage = "Amount must be between 0.01 and 1,000,000")]
    public decimal Amount { get; set; }

    [StringLength(500)]
    public string? Description { get; set; }
}