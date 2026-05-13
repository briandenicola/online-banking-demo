using System.Collections.Generic;
using System.Threading.Tasks;
using TransactionService.Models;
using OnlineBankingDemo.Contracts.Dtos;

namespace TransactionService.Services;

public interface ITransactionService
{
    Task<Transaction> CreateTransactionAsync(CreateTransactionRequest request, string userId);
    Task<Transaction?> GetTransactionByIdAsync(string id, string? accountId = null);
    Task<IEnumerable<Transaction>> GetAccountTransactionsAsync(string accountId, int limit = 50);
    Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50);

    /// <summary>
    /// Re-publish <c>TransactionCreated</c> events for existing transactions onto
    /// the Redis Stream so downstream consumers (e.g. ai-service) can re-process
    /// them. Used to backfill scoring after a Redis purge or schema fix.
    /// </summary>
    Task<int> ReplayCreatedEventsAsync(int limit = 10_000);
}