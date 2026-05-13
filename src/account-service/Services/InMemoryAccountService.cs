using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using AccountService.Models;
using OnlineBankingDemo.Contracts.Dtos;

namespace AccountService.Services;

public class InMemoryAccountService : IAccountService
{
    private readonly ConcurrentDictionary<string, Account> _accounts = new();
    private readonly ILogger<InMemoryAccountService> _logger;

    public InMemoryAccountService(ILogger<InMemoryAccountService> logger)
    {
        _logger = logger;
        SeedDemoAccounts();
    }

    private void SeedDemoAccounts()
    {
        // Seed accounts for testuser (ID: 1)
        _accounts["acct-1-checking"] = new Account
        {
            Id = "acct-1-checking",
            UserId = "1",
            AccountNumber = "ACC10000001",
            AccountType = global::AccountService.Constants.AccountTypes.Checking,
            Balance = 3250.75m,
            Currency = global::AccountService.Constants.Currencies.USD
        };
        _accounts["acct-1-savings"] = new Account
        {
            Id = "acct-1-savings",
            UserId = "1",
            AccountNumber = "ACC10000002",
            AccountType = global::AccountService.Constants.AccountTypes.Savings,
            Balance = 8500.00m,
            Currency = global::AccountService.Constants.Currencies.USD
        };

        // Seed accounts for demo user (ID: 2)
        _accounts["acct-2-checking"] = new Account
        {
            Id = "acct-2-checking",
            UserId = "2",
            AccountNumber = "ACC20000001",
            AccountType = global::AccountService.Constants.AccountTypes.Checking,
            Balance = 5432.10m,
            Currency = global::AccountService.Constants.Currencies.USD
        };
        _accounts["acct-2-savings"] = new Account
        {
            Id = "acct-2-savings",
            UserId = "2",
            AccountNumber = "ACC20000002",
            AccountType = global::AccountService.Constants.AccountTypes.Savings,
            Balance = 12750.00m,
            Currency = global::AccountService.Constants.Currencies.USD
        };

        _logger.LogInformation("Seeded demo accounts for users 1 and 2");
    }

    public Task<Account> CreateAccountAsync(string userId, CreateAccountRequest request)
    {
        var account = new Account
        {
            Id = Guid.NewGuid().ToString(),
            UserId = userId,
            AccountNumber = GenerateAccountNumber(),
            AccountType = request.AccountType,
            Balance = request.InitialBalance,
            Currency = request.Currency ?? global::AccountService.Constants.Currencies.USD
        };

        _accounts[account.Id] = account;
        _logger.LogInformation("Created account {AccountId} for user {UserId}", account.Id, userId);
        return Task.FromResult(account);
    }

    public Task<Account?> GetAccountByIdAsync(string id)
    {
        _accounts.TryGetValue(id, out var account);
        return Task.FromResult(account);
    }

    public Task<System.Collections.Generic.IEnumerable<Account>> GetUserAccountsAsync(string userId)
    {
        var accounts = _accounts.Values.Where(a => a.UserId == userId);
        return Task.FromResult(accounts);
    }

    public Task<Account?> GetAccountByNumberAsync(string accountNumber)
    {
        var account = _accounts.Values.FirstOrDefault(a => a.AccountNumber == accountNumber);
        return Task.FromResult(account);
    }

    public Task<Account> UpdateBalanceAsync(string accountId, decimal amount)
    {
        if (!_accounts.TryGetValue(accountId, out var account))
            throw new InvalidOperationException("Account not found");

        account.Balance += amount;
        _accounts[accountId] = account;
        return Task.FromResult(account);
    }

    private string GenerateAccountNumber()
    {
        var random = new Random();
        return $"{(global::AccountService.Constants.AccountNumberPrefix)}{random.Next(10000000, 99999999)}";
    }
}