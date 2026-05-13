using System.Collections.Concurrent;
using TransactionService.Models;

namespace TransactionService.Repositories;

/// <summary>
/// In-memory <see cref="ITransactionRepository"/> for development / test runs.
/// </summary>
public class InMemoryTransactionRepository : ITransactionRepository
{
    private readonly ConcurrentDictionary<string, Transaction> _transactions = new();

    public InMemoryTransactionRepository()
    {
        SeedDemoTransactions();
    }

    public void Seed(Transaction txn) => _transactions[txn.Id] = txn;

    private void SeedDemoTransactions()
    {
        var now = DateTime.UtcNow;

        var demoChecking = new[]
        {
            new Transaction { Id = "txn-demo-1", AccountId = "acct-2-checking", Amount = -85.50m,  Type = Constants.TransactionTypes.Debit,  Description = "Electric Company Payment", Category = "Utilities",       Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-demo-2", AccountId = "acct-2-checking", Amount = -42.99m,  Type = Constants.TransactionTypes.Debit,  Description = "Grocery Store",            Category = "Groceries",       Timestamp = now.AddDays(-2) },
            new Transaction { Id = "txn-demo-3", AccountId = "acct-2-checking", Amount = 3200.00m, Type = Constants.TransactionTypes.Credit, Description = "Direct Deposit - Payroll", Category = "Income",          Timestamp = now.AddDays(-3) },
            new Transaction { Id = "txn-demo-4", AccountId = "acct-2-checking", Amount = -15.00m,  Type = Constants.TransactionTypes.Debit,  Description = "Netflix Subscription",     Category = "Entertainment",   Timestamp = now.AddDays(-5) },
            new Transaction { Id = "txn-demo-5", AccountId = "acct-2-checking", Amount = -127.30m, Type = Constants.TransactionTypes.Debit,  Description = "Gas Station",              Category = "Transportation",  Timestamp = now.AddDays(-7) },
        };

        var demoSavings = new[]
        {
            new Transaction { Id = "txn-demo-6", AccountId = "acct-2-savings",  Amount = 500.00m,  Type = Constants.TransactionTypes.Credit, Description = "Transfer from Checking",   Category = Constants.Categories.Transfer, Timestamp = now.AddDays(-4) },
            new Transaction { Id = "txn-demo-7", AccountId = "acct-2-savings",  Amount = 25.00m,   Type = Constants.TransactionTypes.Credit, Description = "Interest Payment",         Category = "Income",                      Timestamp = now.AddDays(-10) },
        };

        var testChecking = new[]
        {
            new Transaction { Id = "txn-test-1", AccountId = "acct-1-checking", Amount = -200.00m, Type = Constants.TransactionTypes.Debit,  Description = "ATM Withdrawal",           Category = "Cash",   Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-test-2", AccountId = "acct-1-checking", Amount = 1500.00m, Type = Constants.TransactionTypes.Credit, Description = "Freelance Payment",        Category = "Income", Timestamp = now.AddDays(-6) },
        };

        foreach (var txn in demoChecking.Concat(demoSavings).Concat(testChecking))
        {
            _transactions[txn.Id] = txn;
        }
    }

    public Task<Transaction?> GetByIdAsync(string id, string? accountId = null)
    {
        _transactions.TryGetValue(id, out var txn);
        return Task.FromResult(txn);
    }

    public Task<IEnumerable<Transaction>> GetByAccountIdAsync(string accountId, int limit = 50)
    {
        var results = _transactions.Values
            .Where(t => t.AccountId == accountId)
            .OrderByDescending(t => t.Timestamp)
            .Take(limit)
            .ToList();
        return Task.FromResult<IEnumerable<Transaction>>(results);
    }

    public Task<IEnumerable<Transaction>> GetByUserIdAsync(string userId, int limit = 50)
    {
        var results = _transactions.Values
            .Where(t => t.UserId == userId)
            .OrderByDescending(t => t.Timestamp)
            .Take(limit)
            .ToList();
        return Task.FromResult<IEnumerable<Transaction>>(results);
    }

    public Task<Transaction> CreateAsync(Transaction transaction)
    {
        _transactions[transaction.Id] = transaction;
        return Task.FromResult(transaction);
    }
}
