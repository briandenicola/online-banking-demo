using System.Collections.Concurrent;
using Microsoft.Azure.Cosmos;

namespace TransactionService.Repositories;

/// <summary>
/// In-memory <see cref="IAccountBalanceRepository"/> for development / test runs.
/// Throws a NotFound-equivalent <see cref="CosmosException"/> when an account is
/// missing so the consuming service's existing "account not found" handling
/// behaves identically to the Cosmos-backed adapter.
/// </summary>
public class InMemoryAccountBalanceRepository : IAccountBalanceRepository
{
    private readonly ConcurrentDictionary<string, decimal> _balances = new();

    public InMemoryAccountBalanceRepository()
    {
        // Seed balances matching the InMemoryAccountRepository's demo accounts
        _balances["acct-1-checking"] = 3250.75m;
        _balances["acct-1-savings"] = 8500.00m;
        _balances["acct-2-checking"] = 5432.10m;
        _balances["acct-2-savings"] = 12750.00m;
    }

    public Task<(decimal Balance, string AccountId)> GetBalanceAsync(string accountId)
    {
        if (!_balances.TryGetValue(accountId, out var balance))
        {
            throw new CosmosException("Account not found", System.Net.HttpStatusCode.NotFound, 0, accountId, 0);
        }
        return Task.FromResult((balance, accountId));
    }

    public Task UpdateBalanceAsync(string accountId, decimal amount)
    {
        _balances.AddOrUpdate(accountId, amount, (_, existing) => existing + amount);
        return Task.CompletedTask;
    }
}
