namespace TransactionService.Repositories;

/// <summary>
/// Abstracts balance read/write operations against the accounts container.
/// </summary>
public interface IAccountBalanceRepository
{
    Task<(decimal Balance, string AccountId)> GetBalanceAsync(string accountId);
    Task UpdateBalanceAsync(string accountId, decimal amount);
}
