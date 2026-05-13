using AccountService.Models;

namespace AccountService.Repositories;

public interface IAccountRepository
{
    Task<Account?> GetByIdAsync(string id);
    Task<IEnumerable<Account>> GetByUserIdAsync(string userId);
    Task<Account?> GetByAccountNumberAsync(string accountNumber);
    Task<Account> CreateAsync(Account account);
    Task<Account> UpsertAsync(Account account);
}
