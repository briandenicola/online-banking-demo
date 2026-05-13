using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using TransactionService.Models;
using TransactionService.Repositories;

namespace TransactionService.Services;

public class TransactionService : ITransactionService
{
    private readonly ITransactionRepository _transactionRepository;
    private readonly IAccountBalanceRepository _accountBalanceRepository;
    private readonly IEventPublisher _eventPublisher;
    private readonly ILogger<TransactionService> _logger;
    private const string StreamName = "banking-events";

    public TransactionService(
        ITransactionRepository transactionRepository,
        IAccountBalanceRepository accountBalanceRepository,
        IEventPublisher eventPublisher,
        ILogger<TransactionService> logger)
    {
        _transactionRepository = transactionRepository;
        _accountBalanceRepository = accountBalanceRepository;
        _eventPublisher = eventPublisher;
        _logger = logger;
    }

    public async Task<Transaction> CreateTransactionAsync(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request, string userId)
    {
        // Check balance for debit transactions before creating
        if (IsDebitTransaction(request))
        {
            await ValidateBalanceAsync(request.AccountId, Math.Abs(request.Amount));
        }

        var transaction = new Transaction
        {
            Id = Guid.NewGuid().ToString(),
            AccountId = request.AccountId,
            UserId = userId,
            Amount = request.Amount,
            Currency = request.Currency ?? "USD",
            Type = request.Type,
            Description = request.Description,
            Category = request.Category ?? "Uncategorized",
            RelatedTransactionId = request.RelatedTransactionId
        };

        // Update account balance FIRST — if this fails, no transaction is recorded
        var balanceChange = IsDebitTransaction(request) && transaction.Amount > 0
            ? -transaction.Amount
            : transaction.Amount;
        await UpdateAccountBalanceAsync(transaction.AccountId, balanceChange);

        // Persist transaction only after balance is successfully updated
        await _transactionRepository.CreateAsync(transaction);
        
        // Publish TransactionCreated event to Redis Stream
        await PublishTransactionCreatedEvent(transaction);

        return transaction;
    }

    public async Task<Transaction?> GetTransactionByIdAsync(string id, string? accountId = null)
    {
        return await _transactionRepository.GetByIdAsync(id, accountId);
    }

    public async Task<IEnumerable<Transaction>> GetAccountTransactionsAsync(string accountId, int limit = 50)
    {
        return await _transactionRepository.GetByAccountIdAsync(accountId, limit);
    }

    public async Task<IEnumerable<Transaction>> GetUserTransactionsAsync(string userId, int limit = 50)
    {
        return await _transactionRepository.GetByUserIdAsync(userId, limit);
    }

    private async Task PublishTransactionCreatedEvent(Transaction transaction)
    {
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

            await _eventPublisher.PublishAsync(StreamName, JsonConvert.SerializeObject(eventPayload));

            _logger.LogInformation("Published TransactionCreated event to Redis for transaction {TransactionId}", transaction.Id);
        }
        catch (StackExchange.Redis.RedisConnectionException ex)
        {
            _logger.LogError(ex, "Redis connection failed while publishing TransactionCreated event for transaction {TransactionId}", transaction.Id);
        }
        catch (StackExchange.Redis.RedisException ex)
        {
            _logger.LogError(ex, "Redis error while publishing TransactionCreated event for transaction {TransactionId}", transaction.Id);
        }
    }

    private static bool IsDebitTransaction(OnlineBankingDemo.Contracts.Dtos.CreateTransactionRequest request)
    {
        return request.Amount < 0 ||
               string.Equals(request.Type, "Debit", StringComparison.OrdinalIgnoreCase);
    }

    private async Task ValidateBalanceAsync(string accountId, decimal amount)
    {
        try
        {
            var (balance, _) = await _accountBalanceRepository.GetBalanceAsync(accountId);

            if (balance < amount)
            {
                _logger.LogWarning("Insufficient funds: account {AccountId} balance {Balance} < requested {Amount}",
                    accountId, balance, amount);

                await PublishInsufficientFundsEvent(accountId, balance, amount);

                throw new InsufficientFundsException(accountId, balance, amount);
            }
        }
        catch (InsufficientFundsException)
        {
            throw;
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            _logger.LogError("Account {AccountId} not found in Cosmos DB during balance validation", accountId);
            throw new InvalidOperationException($"Account {accountId} not found. Transaction cannot be processed.", ex);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Balance validation failed for account {AccountId}; rejecting transaction", accountId);
            throw new InvalidOperationException($"Unable to validate balance for account {accountId}. Transaction cannot be processed at this time.", ex);
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

            await _eventPublisher.PublishAsync(StreamName, JsonConvert.SerializeObject(eventPayload));

            _logger.LogInformation("Published InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
        catch (StackExchange.Redis.RedisConnectionException ex)
        {
            _logger.LogError(ex, "Redis connection failed while publishing InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
        catch (StackExchange.Redis.RedisException ex)
        {
            _logger.LogError(ex, "Redis error while publishing InsufficientFundsAttempt event for account {AccountId}", accountId);
        }
    }

    private async Task UpdateAccountBalanceAsync(string accountId, decimal amount)
    {
        try
        {
            await _accountBalanceRepository.UpdateBalanceAsync(accountId, amount);
        }
        catch (CosmosException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            _logger.LogError("Account {AccountId} not found in Cosmos DB during balance update", accountId);
            throw new InvalidOperationException($"Account {accountId} not found. Balance update cannot be completed.", ex);
        }
        catch (CosmosException ex)
        {
            _logger.LogError(ex, "Cosmos DB error updating balance for account {AccountId}", accountId);
            throw;
        }
    }
}