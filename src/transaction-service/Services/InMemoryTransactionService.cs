using System.Collections.Concurrent;
using System.Linq;
using OnlineBankingDemo.Contracts.Dtos;
using TransactionService.Models;

namespace TransactionService.Services;

public class InMemoryTransactionService : ITransactionService
{
    private readonly ConcurrentDictionary<string, Transaction> _transactions = new();

    public Task<Transaction> CreateTransactionAsync(CreateTransactionRequest request)
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
        return Task.FromResult(transaction);
    }

    public Task<Transaction?> GetTransactionByIdAsync(string id)
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
        // In a real implementation, this would filter by user
        var transactions = _transactions.Values
            .OrderByDescending(t => t.Timestamp)
            .Take(limit);
        return Task.FromResult(transactions);
    }
}