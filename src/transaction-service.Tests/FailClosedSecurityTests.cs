using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using TransactionService.Controllers;
using TransactionService.Models;
using TransactionService.Services;
using System.Net.Http;
using System.Security.Claims;
using Xunit;

namespace TransactionService.Tests;

/// <summary>
/// Tests for fail-closed behavior in transaction creation.
/// Related to Issue #27: when dependent services (e.g., account-service) are unreachable,
/// the system should reject the transaction rather than allowing it to proceed unchecked.
/// </summary>
[Trait("Category", "Security")]
public class FailClosedBalanceValidationTests
{
    private readonly Mock<ITransactionService> _transactionServiceMock;
    private readonly Mock<ILogger<TransactionsController>> _loggerMock;
    private readonly TransactionsController _sut;

    public FailClosedBalanceValidationTests()
    {
        _transactionServiceMock = new Mock<ITransactionService>();
        _loggerMock = new Mock<ILogger<TransactionsController>>();
        _sut = new TransactionsController(_transactionServiceMock.Object, _loggerMock.Object);
    }

    private void SetUser(string userId)
    {
        var claims = new List<Claim> { new("userId", userId) };
        var identity = new ClaimsIdentity(claims, "Test");
        var principal = new ClaimsPrincipal(identity);
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext { User = principal }
        };
    }

    /// <summary>
    /// SECURITY GAP (Issue #27): When the account-service is unreachable, the service layer
    /// throws HttpRequestException. The controller does NOT catch this exception, causing a
    /// 500 Internal Server Error to propagate to the client.
    ///
    /// Current behavior: unhandled exception → 500
    /// Expected after fix: controller should catch HttpRequestException and return 503
    /// with message "Transaction temporarily unavailable" to fail closed gracefully.
    /// </summary>
    [Fact]
    public async Task CreateTransaction_WhenAccountServiceUnreachable_ThrowsUnhandledException()
    {
        SetUser("user-1");
        var request = new CreateTransactionRequest
        {
            AccountId = "acc-1",
            Amount = 500m,
            Type = "Debit",
            Description = "Purchase"
        };
        _transactionServiceMock
            .Setup(s => s.CreateTransactionAsync(request, "user-1"))
            .ThrowsAsync(new HttpRequestException("Connection refused"));

        // Current behavior: the exception propagates unhandled from the controller.
        // After fix: should return StatusCode 503 with appropriate message.
        var act = () => _sut.CreateTransaction(request);

        await act.Should().ThrowAsync<HttpRequestException>()
            .WithMessage("*Connection refused*");
    }

    /// <summary>
    /// SECURITY: Verifies that insufficient funds are properly rejected with BadRequest.
    /// This is the correctly-implemented fail-closed path for known validation failures.
    /// </summary>
    [Fact]
    public async Task CreateTransaction_WhenInsufficientBalance_RejectsWithBadRequest()
    {
        SetUser("user-1");
        var request = new CreateTransactionRequest
        {
            AccountId = "acc-1",
            Amount = 10000m,
            Type = "Debit",
            Description = "Large purchase"
        };
        _transactionServiceMock
            .Setup(s => s.CreateTransactionAsync(request, "user-1"))
            .ThrowsAsync(new InsufficientFundsException("acc-1", 500m, 10000m));

        var result = await _sut.CreateTransaction(request);

        result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// Verifies the happy path: when balance is confirmed and the transaction proceeds,
    /// the controller returns CreatedAtAction with the transaction details.
    /// </summary>
    [Fact]
    public async Task CreateTransaction_WhenBalanceConfirmed_TransactionProceeds()
    {
        SetUser("user-1");
        var request = new CreateTransactionRequest
        {
            AccountId = "acc-1",
            Amount = 50m,
            Type = "Debit",
            Description = "Coffee"
        };
        var transaction = new Transaction
        {
            Id = "txn-1",
            AccountId = "acc-1",
            UserId = "user-1",
            Amount = 50m,
            Type = "Debit",
            Description = "Coffee",
            Status = "Completed"
        };
        _transactionServiceMock
            .Setup(s => s.CreateTransactionAsync(request, "user-1"))
            .ReturnsAsync(transaction);

        var result = await _sut.CreateTransaction(request);

        result.Should().BeOfType<CreatedAtActionResult>();
        var createdResult = (CreatedAtActionResult)result;
        createdResult.Value.Should().BeEquivalentTo(transaction);
    }
}
