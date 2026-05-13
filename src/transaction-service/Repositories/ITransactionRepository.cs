using TransactionService.Models;

namespace TransactionService.Repositories;

public interface ITransactionRepository
{
    Task<Transaction?> GetByIdAsync(string id, string? accountId = null);
    Task<IEnumerable<Transaction>> GetByAccountIdAsync(string accountId, int limit = 50);
    Task<IEnumerable<Transaction>> GetByUserIdAsync(string userId, int limit = 50);

    /// <summary>
    /// Cross-partition fetch of every transaction (admin / maintenance only).
    /// Pages are fully drained up to <paramref name="limit"/>.
    /// </summary>
    Task<IEnumerable<Transaction>> GetAllAsync(int limit = 10_000);

    Task<Transaction> CreateAsync(Transaction transaction);
}
