using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Threading.Tasks;
using AccountService.Models;
using AccountService.Repositories;
using Microsoft.Extensions.Logging;
using OnlineBankingDemo.Contracts.Dtos;

namespace AccountService.Services;

public class AccountService : IAccountService
{
    private readonly IAccountRepository _repository;
    private readonly ILogger<AccountService> _logger;

    public AccountService(
        IAccountRepository repository,
        ILogger<AccountService> logger)
    {
        _repository = repository;
        _logger = logger;
    }

    public async Task<Account> CreateAccountAsync(string userId, CreateAccountRequest request)
    {
        var account = new Account
        {
            Id = Guid.NewGuid().ToString(),
            UserId = userId,
            AccountNumber = GenerateAccountNumber(),
            AccountType = request.AccountType,
            Balance = request.InitialBalance,
            Currency = request.Currency ?? "USD"
        };

        var created = await _repository.CreateAsync(account);
        _logger.LogInformation("Created account {AccountId} for user {UserId}", account.Id, userId);
        return created;
    }

    public async Task<Account?> GetAccountByIdAsync(string id)
    {
        return await _repository.GetByIdAsync(id);
    }

    public async Task<IEnumerable<Account>> GetUserAccountsAsync(string userId)
    {
        return await _repository.GetByUserIdAsync(userId);
    }

    public async Task<Account?> GetAccountByNumberAsync(string accountNumber)
    {
        return await _repository.GetByAccountNumberAsync(accountNumber);
    }

    public async Task<Account> UpdateBalanceAsync(string accountId, decimal amount)
    {
        var account = await _repository.GetByIdAsync(accountId);
        if (account == null)
            throw new InvalidOperationException("Account not found");

        account.Balance += amount;
        return await _repository.UpsertAsync(account);
    }

    private string GenerateAccountNumber()
    {
        var number = RandomNumberGenerator.GetInt32(10000000, 99999999);
        return $"ACC{number}";
    }
}