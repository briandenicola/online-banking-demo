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
    private readonly ConcurrentDictionary<string, decimal> _accountBalances = new();
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<InMemoryTransactionService> _logger;
    private const string StreamName = global::TransactionService.Constants.DefaultStreamName;

    public InMemoryTransactionService(
        IConnectionMultiplexer redis,
        ILogger<InMemoryTransactionService> logger)
    {
        _redis = redis;
        _logger = logger;
        SeedDemoData();
    }

    private void SeedDemoData()
    {
        // Seed account balances matching InMemoryAccountService seed data
        _accountBalances["acct-1-checking"] = 3250.75m;
        _accountBalances["acct-1-savings"] = 8500.00m;
        _accountBalances["acct-2-checking"] = 5432.10m;
        _accountBalances["acct-2-savings"] = 12750.00m;

        SeedDemoTransactions();
    }

    private void SeedDemoTransactions()
    {
        var now = DateTime.UtcNow;

        // Transactions for demo user's checking account (acct-2-checking)
        var demoChecking = new[]
        {
            new Transaction { Id = "txn-demo-1", AccountId = "acct-2-checking", Amount = -85.50m, Type = global::TransactionService.Constants.TransactionTypes.Debit, Description = "Electric Company Payment", Category = "Utilities", Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-demo-2", AccountId = "acct-2-checking", Amount = -42.99m, Type = global::TransactionService.Constants.TransactionTypes.Debit, Description = "Grocery Store", Category = "Groceries", Timestamp = now.AddDays(-2) },
            new Transaction { Id = "txn-demo-3", AccountId = "acct-2-checking", Amount = 3200.00m, Type = global::TransactionService.Constants.TransactionTypes.Credit, Description = "Direct Deposit - Payroll", Category = "Income", Timestamp = now.AddDays(-3) },
            new Transaction { Id = "txn-demo-4", AccountId = "acct-2-checking", Amount = -15.00m, Type = global::TransactionService.Constants.TransactionTypes.Debit, Description = "Netflix Subscription", Category = "Entertainment", Timestamp = now.AddDays(-5) },
            new Transaction { Id = "txn-demo-5", AccountId = "acct-2-checking", Amount = -127.30m, Type = global::TransactionService.Constants.TransactionTypes.Debit, Description = "Gas Station", Category = "Transportation", Timestamp = now.AddDays(-7) },
        };

        // Transactions for demo user's savings account (acct-2-savings)
        var demoSavings = new[]
        {
            new Transaction { Id = "txn-demo-6", AccountId = "acct-2-savings", Amount = 500.00m, Type = global::TransactionService.Constants.TransactionTypes.Credit, Description = "Transfer from Checking", Category = "Transfer", Timestamp = now.AddDays(-4) },
            new Transaction { Id = "txn-demo-7", AccountId = "acct-2-savings", Amount = 25.00m, Type = global::TransactionService.Constants.TransactionTypes.Credit, Description = "Interest Payment", Category = "Income", Timestamp = now.AddDays(-10) },
        };

        // Transactions for testuser's checking account (acct-1-checking)
        var testChecking = new[]
        {
            new Transaction { Id = "txn-test-1", AccountId = "acct-1-checking", Amount = -200.00m, Type = global::TransactionService.Constants.TransactionTypes.Debit, Description = "ATM Withdrawal", Category = "Cash", Timestamp = now.AddDays(-1) },
            new Transaction { Id = "txn-test-2", AccountId = "acct-1-checking", Amount = 1500.00m, Type = global::TransactionService.Constants.TransactionTypes.Credit, Description = "Freelance Payment", Category = "Income", Timestamp = now.AddDays(-6) },
        };

        foreach (var txn in demoChecking.Concat(demoSavings).Concat(testChecking))
        {
            _transactions[txn.Id] = txn;
        }

        _logger.LogInformation("Seeded {Count} demo transactions", _transactions.Count);
    }

    public async Task<Transaction> CreateTransactionAsync(CreateTransactionRequest request, string userId)
    {
        // Check balance for debit transactions before creating
        if (IsDebitTransaction(request))
        {
            await ValidateBalanceAsync(request.AccountId, Math.Abs(request.Amount));
        }

        var transaction = new Transaction
        {
            Id = System.Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            UserId = userId,
            Amount = request.Amount,
            Currency = request.Currency ?? global::TransactionService.Constants.Currencies.USD,
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? global::TransactionService.Constants.Categories.Uncategorized
        };
        _transactions[transaction.Id] = transaction;

        // Update account balance (transaction-service owns balance side effects)
        // Debit transactions decrease balance, so negate positive amounts
        var balanceChange = IsDebitTransaction(request) && transaction.Amount > 0
            ? -transaction.Amount
            : transaction.Amount;
        await UpdateAccountBalanceAsync(transaction.AccountId, balanceChange);

        // Publish TransactionCreated event to Redis Stream
        try
        {
            var eventPayload = new
            {
                eventType = global::TransactionService.Constants.EventTypes.TransactionCreated,
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    id = transaction.Id,
                    accountId = transaction.AccountId,
                    userId = transaction.UserId,
                    amount = transaction.Amount,
                    type = transaction.Type,
                    description = transaction.Description,
                    category = transaction.Category
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
            .Where(t => t.UserId == userId)
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }

    private static bool IsDebitTransaction(CreateTransactionRequest request)
    {
        return request.Amount < 0 ||
               string.Equals(request.Type, global::TransactionService.Constants.TransactionTypes.Debit, StringComparison.OrdinalIgnoreCase);
    }

    private async Task ValidateBalanceAsync(string accountId, decimal amount)
    {
        if (!_accountBalances.TryGetValue(accountId, out var balance))
        {
            _logger.LogError("Account {AccountId} not found during balance validation", accountId);
            throw new InvalidOperationException($"Account {accountId} not found. Transaction cannot be processed.");
        }

        if (balance < amount)
        {
            _logger.LogWarning("Insufficient funds: account {AccountId} balance {Balance} < requested {Amount}",
                accountId, balance, amount);

            await PublishInsufficientFundsEvent(accountId, balance, amount);

            throw new InsufficientFundsException(accountId, balance, amount);
        }
    }

    private async Task PublishInsufficientFundsEvent(string accountId, decimal balance, decimal requestedAmount)
    {
        try
        {
            var eventPayload = new
            {
                eventType = global::TransactionService.Constants.EventTypes.InsufficientFundsAttempt,
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    accountId,
                    currentBalance = balance,
                    requestedAmount,
                    type = global::TransactionService.Constants.TransactionTypes.Debit
                }
            };

            var db = _redis.GetDatabase();
            await db.StreamAddAsync(StreamName, new NameValueEntry[]
            {
                new("payload", JsonConvert.SerializeObject(eventPayload))
            });

            _logger.LogInformation("Published InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to publish InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
    }

    private Task UpdateAccountBalanceAsync(string accountId, decimal amount)
    {
        _accountBalances.AddOrUpdate(accountId, amount, (_, existing) => existing + amount);
        _logger.LogInformation("Updated account {AccountId} balance by {Amount}", accountId, amount);
        return Task.CompletedTask;
    }
}