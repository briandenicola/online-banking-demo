namespace OnlineBankingDemo.Contracts.Dtos;

public class CreateTransferRequest
{
    public string FromAccountNumber { get; set; } = null!;
    public string ToAccountNumber { get; set; } = null!;
    public decimal Amount { get; set; }
    public string? Description { get; set; }
}