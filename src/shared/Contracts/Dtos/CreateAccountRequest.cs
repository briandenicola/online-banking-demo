using System.ComponentModel.DataAnnotations;

namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateAccountRequest
{
    [Required]
    [StringLength(50)]
    [RegularExpression("^(Checking|Savings|MoneyMarket|CD|Loan|Credit)$",
        ErrorMessage = "AccountType must be one of: Checking, Savings, MoneyMarket, CD, Loan, Credit.")]
    public string AccountType { get; set; } = null!;

    [Range(0, 10000000)]
    public decimal InitialBalance { get; set; }

    [StringLength(3, MinimumLength = 3)]
    [RegularExpression("^[A-Z]{3}$", ErrorMessage = "Currency must be an ISO 4217 3-letter code (e.g. USD).")]
    public string? Currency { get; set; }
}