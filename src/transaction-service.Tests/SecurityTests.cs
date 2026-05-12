using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using TransactionService.Controllers;
using TransactionService.Models;
using TransactionService.Services;
using System.Security.Claims;
using Xunit;

namespace TransactionService.Tests;

[Trait("Category", "Security")]
public class TransactionsControllerSecurityTests
{
    private readonly Mock<ITransactionService> _transactionServiceMock;
    private readonly Mock<ILogger<TransactionsController>> _loggerMock;
    private readonly TransactionsController _sut;

    public TransactionsControllerSecurityTests()
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

    private void SetNoUser()
    {
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext()
        };
    }

    /// <summary>
    /// SECURITY: Verifies that CreateTransaction rejects unauthenticated requests.
    /// Without a valid JWT userId claim, the controller returns Unauthorized.
    /// </summary>
    [Fact]
    public async Task CreateTransaction_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();
        var request = new CreateTransactionRequest
        {
            AccountId = "acc-1",
            Amount = 100m,
            Type = "Debit",
            Description = "Test"
        };

        var result = await _sut.CreateTransaction(request);

        result.Should().BeOfType<UnauthorizedResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that CreateTransaction correctly passes the authenticated
    /// user's JWT-derived userId to the service layer, preventing identity spoofing.
    /// </summary>
    [Fact]
    public async Task CreateTransaction_AuthenticatedUser_PassesUserIdToService()
    {
        SetUser("user-1");
        var request = new CreateTransactionRequest
        {
            AccountId = "acc-1",
            Amount = 100m,
            Type = "Credit",
            Description = "Deposit"
        };
        var transaction = new Transaction
        {
            Id = "txn-1",
            AccountId = "acc-1",
            UserId = "user-1",
            Amount = 100m,
            Type = "Credit",
            Description = "Deposit"
        };
        _transactionServiceMock
            .Setup(s => s.CreateTransactionAsync(request, "user-1"))
            .ReturnsAsync(transaction);

        var result = await _sut.CreateTransaction(request);

        result.Should().BeOfType<CreatedAtActionResult>();
        _transactionServiceMock.Verify(
            s => s.CreateTransactionAsync(request, "user-1"), Times.Once);
    }

    /// <summary>
    /// SECURITY: Verifies that GetTransaction enforces ownership checks.
    /// When an authenticated user requests a transaction belonging to another user,
    /// the controller returns NotFound to prevent cross-user data access and
    /// avoid leaking transaction existence information.
    /// </summary>
    [Fact]
    public async Task GetTransaction_OtherUsersTransaction_ReturnsNotFound()
    {
        SetUser("attacker");
        var victimTransaction = new Transaction
        {
            Id = "txn-victim",
            AccountId = "acc-victim",
            UserId = "victim",
            Amount = 5000m,
            Type = "Credit",
            Description = "Salary"
        };
        _transactionServiceMock
            .Setup(s => s.GetTransactionByIdAsync("txn-victim", null))
            .ReturnsAsync(victimTransaction);

        var result = await _sut.GetTransaction("txn-victim");

        result.Should().BeOfType<NotFoundResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetAccountTransactions is scoped to the authenticated user.
    /// The controller first fetches the user's own transactions, then filters by accountId,
    /// ensuring a user cannot access another user's account transactions even if they
    /// know the accountId.
    /// </summary>
    [Fact]
    public async Task GetAccountTransactions_OnlyReturnsAuthenticatedUsersTransactions()
    {
        SetUser("user-1");
        var userTransactions = new List<Transaction>
        {
            new() { Id = "txn-1", AccountId = "acc-1", UserId = "user-1", Amount = 100m, Type = "Credit", Description = "Deposit" },
            new() { Id = "txn-2", AccountId = "acc-2", UserId = "user-1", Amount = 50m, Type = "Debit", Description = "Purchase" }
        };
        _transactionServiceMock
            .Setup(s => s.GetUserTransactionsAsync("user-1", 50))
            .ReturnsAsync(userTransactions);

        // Request transactions for acc-1 — should only return txn-1
        var result = await _sut.GetAccountTransactions("acc-1");

        result.Should().BeOfType<OkObjectResult>();
        var okResult = (OkObjectResult)result;
        var transactions = okResult.Value as IEnumerable<Transaction>;
        transactions.Should().NotBeNull();
        transactions!.Should().AllSatisfy(t => t.AccountId.Should().Be("acc-1"));

        // Verify it called GetUserTransactionsAsync with the authenticated userId
        _transactionServiceMock.Verify(
            s => s.GetUserTransactionsAsync("user-1", 50), Times.Once);
        // Verify it did NOT call GetAccountTransactionsAsync directly (which would bypass ownership)
        _transactionServiceMock.Verify(
            s => s.GetAccountTransactionsAsync(It.IsAny<string>(), It.IsAny<int>()),
            Times.Never,
            "Controller should filter through user's transactions, not query account directly");
    }

    /// <summary>
    /// SECURITY: Verifies that GetAccountTransactions for an account the user doesn't own
    /// returns an empty result set rather than the other user's transactions.
    /// </summary>
    [Fact]
    public async Task GetAccountTransactions_OtherUsersAccount_ReturnsEmpty()
    {
        SetUser("attacker");
        // Attacker has no transactions
        _transactionServiceMock
            .Setup(s => s.GetUserTransactionsAsync("attacker", 50))
            .ReturnsAsync(new List<Transaction>());

        var result = await _sut.GetAccountTransactions("victims-account-id");

        result.Should().BeOfType<OkObjectResult>();
        var okResult = (OkObjectResult)result;
        var transactions = okResult.Value as IEnumerable<Transaction>;
        transactions.Should().NotBeNull();
        transactions!.Should().BeEmpty();
    }

    /// <summary>
    /// SECURITY: Verifies that GetUserTransactions only returns the authenticated user's
    /// transactions by passing the JWT-derived userId to the service layer.
    /// </summary>
    [Fact]
    public async Task GetUserTransactions_OnlyReturnsAuthenticatedUsersTransactions()
    {
        SetUser("user-1");
        var userTransactions = new List<Transaction>
        {
            new() { Id = "txn-1", AccountId = "acc-1", UserId = "user-1", Amount = 100m, Type = "Credit", Description = "Deposit" }
        };
        _transactionServiceMock
            .Setup(s => s.GetUserTransactionsAsync("user-1", 50))
            .ReturnsAsync(userTransactions);

        var result = await _sut.GetUserTransactions();

        result.Should().BeOfType<OkObjectResult>();
        _transactionServiceMock.Verify(s => s.GetUserTransactionsAsync("user-1", 50), Times.Once);
    }

    /// <summary>
    /// SECURITY: Verifies that GetTransactions (the general listing endpoint)
    /// requires authentication and rejects unauthenticated requests.
    /// </summary>
    [Fact]
    public async Task GetTransactions_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();

        var result = await _sut.GetTransactions();

        result.Should().BeOfType<UnauthorizedResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetTransaction requires authentication.
    /// Without a valid JWT userId claim, the controller returns Unauthorized.
    /// </summary>
    [Fact]
    public async Task GetTransaction_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();

        var result = await _sut.GetTransaction("txn-1");

        result.Should().BeOfType<UnauthorizedResult>();
    }
}
