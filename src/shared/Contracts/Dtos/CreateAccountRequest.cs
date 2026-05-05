using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateAccountRequest
{
    [Required]
    [StringLength(50)]
    public string AccountType { get; set; } = null!;

    [Range(0, 10000000)]
    public decimal InitialBalance { get; set; }

    [StringLength(10)]
    public string? Currency { get; set; }
}