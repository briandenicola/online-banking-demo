using System.Collections.Concurrent;
using AccountService.Models;

namespace AccountService.Repositories;

/// <summary>
/// In-memory <see cref="IAccountRepository"/> for development / test runs.
/// Storage adapter only — all business logic lives in <see cref="Services.AccountService"/>.
/// </summary>
public class InMemoryAccountRepository : IAccountRepository
{
    private readonly ConcurrentDictionary<string, Account> _accounts = new();

    public InMemoryAccountRepository()
    {
        SeedDemoAccounts();
    }

    private void SeedDemoAccounts()
    {
        _accounts["acct-1-checking"] = new Account
        {
            Id = "acct-1-checking",
            UserId = "1",
            AccountNumber = "ACC10000001",
            AccountType = Constants.AccountTypes.Checking,
            Balance = 3250.75m,
            Currency = Constants.Currencies.USD,
        };
        _accounts["acct-1-savings"] = new Account
        {
            Id = "acct-1-savings",
            UserId = "1",
            AccountNumber = "ACC10000002",
            AccountType = Constants.AccountTypes.Savings,
            Balance = 8500.00m,
            Currency = Constants.Currencies.USD,
        };
        _accounts["acct-2-checking"] = new Account
        {
            Id = "acct-2-checking",
            UserId = "2",
            AccountNumber = "ACC20000001",
            AccountType = Constants.AccountTypes.Checking,
            Balance = 5432.10m,
            Currency = Constants.Currencies.USD,
        };
        _accounts["acct-2-savings"] = new Account
        {
            Id = "acct-2-savings",
            UserId = "2",
            AccountNumber = "ACC20000002",
            AccountType = Constants.AccountTypes.Savings,
            Balance = 12750.00m,
            Currency = Constants.Currencies.USD,
        };
    }

    public Task<Account?> GetByIdAsync(string id)
    {
        _accounts.TryGetValue(id, out var account);
        return Task.FromResult(account);
    }

    public Task<IEnumerable<Account>> GetByUserIdAsync(string userId)
    {
        var accounts = _accounts.Values.Where(a => a.UserId == userId).ToList();
        return Task.FromResult<IEnumerable<Account>>(accounts);
    }

    public Task<Account?> GetByAccountNumberAsync(string accountNumber)
    {
        var account = _accounts.Values.FirstOrDefault(a => a.AccountNumber == accountNumber);
        return Task.FromResult(account);
    }

    public Task<Account> CreateAsync(Account account)
    {
        _accounts[account.Id] = account;
        return Task.FromResult(account);
    }

    public Task<Account> UpsertAsync(Account account)
    {
        _accounts[account.Id] = account;
        return Task.FromResult(account);
    }
}
