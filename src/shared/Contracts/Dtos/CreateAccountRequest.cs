namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateAccountRequest
{
    public string AccountType { get; set; } = null!;
    public decimal InitialBalance { get; set; }
    public string? Currency { get; set; }
}