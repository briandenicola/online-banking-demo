using System.Collections.Concurrent;
using System.Linq;
using Newtonsoft.Json;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using TransactionService.Models;

namespace TransactionService.Services;

public class InMemoryTransactionService : ITransactionService
{
    private readonly ConcurrentDictionary<string, Transaction> _transactions = new();
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<InMemoryTransactionService> _logger;
    private const string StreamName = "banking-events";

    public InMemoryTransactionService(IConnectionMultiplexer redis, ILogger<InMemoryTransactionService> logger)
    {
        _redis = redis;
        _logger = logger;
        SeedDemoTransactions();
    }

    private void SeedDemoTransactions()
    {
        var now = DateTime.UtcNow;

        // Transactions for demo user's checking account (acct-2-checking)
        var demoChecking = new[]
        {
            new Transaction { Id = "txn-demo-1", AccountId = "acct-2-checking", Amount = -85.50m, Type = "Debit", Description = "Electric Company Payment", Category = "Utilities", Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-demo-2", AccountId = "acct-2-checking", Amount = -42.99m, Type = "Debit", Description = "Grocery Store", Category = "Groceries", Timestamp = now.AddDays(-2) },
            new Transaction { Id = "txn-demo-3", AccountId = "acct-2-checking", Amount = 3200.00m, Type = "Credit", Description = "Direct Deposit - Payroll", Category = "Income", Timestamp = now.AddDays(-3) },
            new Transaction { Id = "txn-demo-4", AccountId = "acct-2-checking", Amount = -15.00m, Type = "Debit", Description = "Netflix Subscription", Category = "Entertainment", Timestamp = now.AddDays(-5) },
            new Transaction { Id = "txn-demo-5", AccountId = "acct-2-checking", Amount = -127.30m, Type = "Debit", Description = "Gas Station", Category = "Transportation", Timestamp = now.AddDays(-7) },
        };

        // Transactions for demo user's savings account (acct-2-savings)
        var demoSavings = new[]
        {
            new Transaction { Id = "txn-demo-6", AccountId = "acct-2-savings", Amount = 500.00m, Type = "Credit", Description = "Transfer from Checking", Category = "Transfer", Timestamp = now.AddDays(-4) },
            new Transaction { Id = "txn-demo-7", AccountId = "acct-2-savings", Amount = 25.00m, Type = "Credit", Description = "Interest Payment", Category = "Income", Timestamp = now.AddDays(-10) },
        };

        // Transactions for testuser's checking account (acct-1-checking)
        var testChecking = new[]
        {
            new Transaction { Id = "txn-test-1", AccountId = "acct-1-checking", Amount = -200.00m, Type = "Debit", Description = "ATM Withdrawal", Category = "Cash", Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-test-2", AccountId = "acct-1-checking", Amount = 1500.00m, Type = "Credit", Description = "Freelance Payment", Category = "Income", Timestamp = now.AddDays(-6) },
        };

        foreach (var txn in demoChecking.Concat(demoSavings).Concat(testChecking))
        {
            _transactions[txn.Id] = txn;
        }

        _logger.LogInformation("Seeded {Count} demo transactions", _transactions.Count);
    }

    public async Task<Transaction> CreateTransactionAsync(CreateTransactionRequest request)
    {
        var transaction = new Transaction
        {
            Id = System.Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            Amount = request.Amount,
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized"
        };
        _transactions[transaction.Id] = transaction;

        // Publish TransactionCreated event to Redis Stream
        try
        {
            var eventPayload = new
            {
                eventType = "TransactionCreated",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    accountId = transaction.AccountId,
                    amount = transaction.Amount,
                    type = transaction.Type,
                    description = transaction.Description
                }
            };

            var db = _redis.GetDatabase();
            await db.StreamAddAsync(StreamName, new NameValueEntry[]
            {
                new("payload", JsonConvert.SerializeObject(eventPayload))
            });

            _logger.LogInformation("Published TransactionCreated event to Redis for transaction {TransactionId}", transaction.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to publish event to Redis for transaction {TransactionId}", transaction.Id);
        }

        return transaction;
    }

    public Task<Transaction?> GetTransactionByIdAsync(string id, string? accountId = null)
    {
        _transactions.TryGetValue(id, out var transaction);
        return Task.FromResult(transaction);
    }

    public Task<IEnumerable<Transaction>> GetAccountTransactionsAsync(string accountId, int limit = 50)
    {
        var transactions = _transactions.Values
            .Where(t => t.AccountId == accountId)
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }

    public Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50)
    {
        var transactions = _transactions.Values
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }
}