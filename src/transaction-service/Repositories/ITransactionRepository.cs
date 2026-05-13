using TransactionService.Models;

namespace TransactionService.Repositories;

public interface ITransactionRepository
{
    Task<Transaction?> GetByIdAsync(string id, string? accountId = null);
    Task<IEnumerable<Transaction>> GetByAccountIdAsync(string accountId, int limit = 50);
    Task<IEnumerable<Transaction>> GetByUserIdAsync(string userId, int limit = 50);
    Task<Transaction> CreateAsync(Transaction transaction);
}
