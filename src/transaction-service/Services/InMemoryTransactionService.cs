using System.Collections.Concurrent;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using Microsoft.AspNetCore.Http;
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
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _configuration;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private const string StreamName = "banking-events";

    public InMemoryTransactionService(
        IConnectionMultiplexer redis,
        ILogger<InMemoryTransactionService> logger,
        IHttpClientFactory httpClientFactory,
        IConfiguration configuration,
        IHttpContextAccessor httpContextAccessor)
    {
        _redis = redis;
        _logger = logger;
        _httpClientFactory = httpClientFactory;
        _configuration = configuration;
        _httpContextAccessor = httpContextAccessor;
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
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized"
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
                eventType = "TransactionCreated",
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
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }

    private static bool IsDebitTransaction(CreateTransactionRequest request)
    {
        return request.Amount < 0 ||
               string.Equals(request.Type, "Debit", StringComparison.OrdinalIgnoreCase);
    }

    private async Task ValidateBalanceAsync(string accountId, decimal amount)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            _logger.LogWarning("AccountService URL not configured; skipping balance validation");
            return;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();
            var response = await client.GetAsync($"{accountServiceUrl}/api/accounts/{accountId}");
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("Could not fetch account {AccountId} for balance check (HTTP {StatusCode})", accountId, response.StatusCode);
                return;
            }

            var json = await response.Content.ReadAsStringAsync();
            var account = System.Text.Json.JsonSerializer.Deserialize<AccountInfo>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            if (account != null && account.Balance < amount)
            {
                _logger.LogWarning("Insufficient funds: account {AccountId} balance {Balance} < requested {Amount}",
                    accountId, account.Balance, amount);

                // Publish anomaly event for insufficient funds attempt
                await PublishInsufficientFundsEvent(accountId, account.Balance, amount);

                throw new InsufficientFundsException(accountId, account.Balance, amount);
            }
        }
        catch (InsufficientFundsException)
        {
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Balance validation failed for account {AccountId}; allowing transaction to proceed", accountId);
        }
    }

    private async Task PublishInsufficientFundsEvent(string accountId, decimal balance, decimal requestedAmount)
    {
        try
        {
            var eventPayload = new
            {
                eventType = "InsufficientFundsAttempt",
                timestamp = DateTime.UtcNow.ToString("o"),
                data = new
                {
                    accountId,
                    currentBalance = balance,
                    requestedAmount,
                    type = "Debit"
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

    private async Task UpdateAccountBalanceAsync(string accountId, decimal amount)
    {
        var accountServiceUrl = _configuration["Services:AccountService"];
        if (string.IsNullOrEmpty(accountServiceUrl))
        {
            _logger.LogWarning("AccountService URL not configured; skipping balance update");
            return;
        }

        try
        {
            var client = _httpClientFactory.CreateClient();
            
            // Forward JWT token for service-to-service authentication
            var authHeader = _httpContextAccessor.HttpContext?.Request.Headers["Authorization"].FirstOrDefault();
            if (!string.IsNullOrEmpty(authHeader))
            {
                client.DefaultRequestHeaders.Authorization = AuthenticationHeaderValue.Parse(authHeader);
            }
            
            var requestBody = JsonConvert.SerializeObject(new { Amount = amount });
            var content = new StringContent(requestBody, System.Text.Encoding.UTF8, "application/json");
            
            var response = await client.PostAsync($"{accountServiceUrl}/api/accounts/{accountId}/balance", content);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogError("Failed to update account balance for {AccountId} (HTTP {StatusCode})", accountId, response.StatusCode);
            }
            else
            {
                _logger.LogInformation("Updated account {AccountId} balance by {Amount}", accountId, amount);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to call account-service to update balance for account {AccountId}", accountId);
        }
    }

    private class AccountInfo
    {
        public string Id { get; set; } = null!;
        public decimal Balance { get; set; }
    }
}