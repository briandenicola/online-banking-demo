using System.Collections.Generic;
using System.Threading.Tasks;
using AccountService.Models;
using OnlineBankingDemo.Contracts.Dtos;

namespace AccountService.Services;

public interface IAccountService
{
    Task<Account> CreateAccountAsync(string userId, CreateAccountRequest request);
    Task<Account?> GetAccountByIdAsync(string id);
    Task<IEnumerable<Account>> GetUserAccountsAsync(string userId);
    Task<Account?> GetAccountByNumberAsync(string accountNumber);
    Task<Account> UpdateBalanceAsync(string accountId, decimal amount);
}