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
}