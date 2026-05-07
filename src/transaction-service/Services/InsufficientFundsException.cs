using System;

namespace TransactionService.Services;

public class InsufficientFundsException : Exception
{
    public string AccountId { get; }
    public decimal CurrentBalance { get; }
    public decimal RequestedAmount { get; }

    public InsufficientFundsException(string accountId, decimal currentBalance, decimal requestedAmount)
        : base($"Insufficient funds: account {accountId} has balance {currentBalance:C} but transaction requires {requestedAmount:C}")
    {
        AccountId = accountId;
        CurrentBalance = currentBalance;
        RequestedAmount = requestedAmount;
    }
}
