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
    /// SECURITY (ruling §B2.2): the endpoint asks the question it is documented to answer.
    ///
    /// <para>
    /// It used to read the CALLER's transactions and narrow them to the accountId, and the two
    /// tests that stood here asserted exactly that — one of them named
    /// <c>..._OtherUsersAccount_ReturnsEmpty</c>, which pinned the defect in place as if it were
    /// the requirement. It is worth recording what they were: for any non-owner the endpoint
    /// returned <c>200 []</c> BY CONSTRUCTION, for every account in the bank, and that empty
    /// array then passed through a correct projection and a correct completeness gate on its way
    /// to a supervisor as grounds for reasoning.
    /// </para>
    /// </summary>
    [Fact]
    public async Task GetAccountTransactions_QueriesByAccountId_NotByCaller()
    {
        SetUser("user-1");
        _transactionServiceMock
            .Setup(s => s.GetAccountTransactionsAsync("acc-1", 50))
            .ReturnsAsync(new List<Transaction>
            {
                new() { Id = "txn-1", AccountId = "acc-1", UserId = "user-1", Amount = 100m, Type = "Credit", Description = "Deposit" }
            });

        var result = await _sut.GetAccountTransactions("acc-1");

        result.Should().BeOfType<OkObjectResult>();
        _transactionServiceMock.Verify(s => s.GetAccountTransactionsAsync("acc-1", 50), Times.Once);
        _transactionServiceMock.Verify(
            s => s.GetUserTransactionsAsync(It.IsAny<string>(), It.IsAny<int>()),
            Times.Never,
            "the caller-derived filter is DELETED, not kept as a fallback: a fallback preserves "
            + "the exact path that produces the lie");
    }

    /// <summary>
    /// SECURITY: an ordinary customer reading another customer's account is now told NO, rather
    /// than told that the account has no history.
    /// </summary>
    [Fact]
    public async Task GetAccountTransactions_OtherUsersAccount_ReturnsForbidden()
    {
        SetUser("attacker");
        _transactionServiceMock
            .Setup(s => s.GetAccountTransactionsAsync("victims-account-id", 50))
            .ReturnsAsync(new List<Transaction>
            {
                new() { Id = "txn-v", AccountId = "victims-account-id", UserId = "victim", Amount = 5000m, Type = "Credit", Description = "Salary" }
            });

        var result = await _sut.GetAccountTransactions("victims-account-id");

        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    /// <summary>
    /// SECURITY: the victim's rows do not appear in the denied response body either. A 403 whose
    /// body still carries the data would be a status code apologising for a leak.
    /// </summary>
    [Fact]
    public async Task GetAccountTransactions_DeniedResponse_CarriesNoTransactionData()
    {
        SetUser("attacker");
        _transactionServiceMock
            .Setup(s => s.GetAccountTransactionsAsync("victims-account-id", 50))
            .ReturnsAsync(new List<Transaction>
            {
                new() { Id = "txn-v", AccountId = "victims-account-id", UserId = "victim", Amount = 5000m, Type = "Credit", Description = "Salary" }
            });

        var result = (ObjectResult)await _sut.GetAccountTransactions("victims-account-id");

        System.Text.Json.JsonSerializer.Serialize(result.Value)
            .Should().NotContain("txn-v").And.NotContain("5000");
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

/// <summary>
/// Ruling §B2, one test per row of the table, driven through the controller.
///
/// <para>
/// Every row is asserted on what the ENDPOINT produces. The failure mode to avoid here is a test
/// that passes because a fixture supplied a 403 rather than because the endpoint decided on one,
/// which would stay green with the entire check deleted — so the only thing stubbed is the
/// repository read, and the status under assertion is always the controller's own.
/// </para>
/// </summary>
[Trait("Category", "Security")]
public class BankerReadsACustomersTransactionsTests
{
    private readonly Mock<ITransactionService> _transactionServiceMock = new();
    private readonly Mock<ILogger<TransactionsController>> _loggerMock = new();
    private readonly TransactionsController _sut;

    public BankerReadsACustomersTransactionsTests()
    {
        _sut = new TransactionsController(_transactionServiceMock.Object, _loggerMock.Object);
    }

    private void SetUser(string userId, params string[] roles)
    {
        var claims = new List<Claim> { new("userId", userId) };
        claims.AddRange(roles.Select(r => new Claim(ClaimTypes.Role, r)));
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext { User = new ClaimsPrincipal(new ClaimsIdentity(claims, "Test")) }
        };
    }

    private void LedgerFor(string accountId, params Transaction[] rows) =>
        _transactionServiceMock.Setup(s => s.GetAccountTransactionsAsync(accountId, 50))
            .ReturnsAsync(rows.ToList());

    private static Transaction CaseyRow(string id) =>
        new() { Id = id, AccountId = "acc-casey", UserId = "casey", Amount = 120m, Type = "Debit", Description = "Groceries" };

    [Theory]
    [InlineData("banker")]
    [InlineData("supervisor")]
    public async Task ABankingAuthority_ReadsACustomersLedger(string role)
    {
        // The case Brian asked for: the banker works Casey's case and sees Casey's history.
        SetUser("banker-1", role);
        LedgerFor("acc-casey", CaseyRow("txn-1"), CaseyRow("txn-2"));

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().BeOfType<OkObjectResult>()
            .Which.Value.Should().BeAssignableTo<IEnumerable<Transaction>>()
            .Which.Should().HaveCount(2);
    }

    [Fact]
    public async Task AnAdmin_IsForbidden()
    {
        // §B1.1: platform authority is not banking authority.
        SetUser("admin-1", "admin", "Admin");
        LedgerFor("acc-casey", CaseyRow("txn-1"));

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    [Fact]
    public async Task TheOwner_StillReadsTheirOwnLedgerWithoutAnyRole()
    {
        SetUser("casey");
        LedgerFor("acc-casey", CaseyRow("txn-1"));

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task APermittedCallerWithACleanLedger_GetsAnEmptyArray_AndItIsTrue()
    {
        // THE ROW THAT MATTERS. `200 []` is now the only way to say "genuinely nothing", and it
        // is reached only by a caller who was actually entitled to ask.
        SetUser("banker-1", "banker");
        LedgerFor("acc-casey");

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().BeOfType<OkObjectResult>()
            .Which.Value.Should().BeAssignableTo<IEnumerable<Transaction>>()
            .Which.Should().BeEmpty();
    }

    [Fact]
    public async Task AnUnprivilegedStranger_IsNeverAnsweredWithAnEmptyArray()
    {
        // The defect's whole shape, guarded directly: a true-looking answer produced by an
        // accident of the query. This service does not own accounts, so a non-privileged
        // caller's entitlement can only be derived from the rows — and an EMPTY result derives
        // nothing. It therefore is not the table's "permitted and empty" row, and answering
        // `200 []` on it would rebuild the lie one field over. Errs closed; the copilot always
        // holds `banker`, and nothing else in the repo calls this endpoint.
        SetUser("attacker");
        LedgerFor("acc-casey");

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().NotBeOfType<OkObjectResult>(
            "an empty array from this endpoint must mean 'this ledger is empty', never 'you are "
            + "not allowed to know'");
        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    [Fact]
    public async Task AnUnauthenticatedCaller_IsRejectedBeforeTheLedgerIsRead()
    {
        _sut.ControllerContext = new ControllerContext { HttpContext = new DefaultHttpContext() };

        var result = await _sut.GetAccountTransactions("acc-casey");

        result.Should().BeOfType<UnauthorizedResult>();
        _transactionServiceMock.Verify(
            s => s.GetAccountTransactionsAsync(It.IsAny<string>(), It.IsAny<int>()), Times.Never);
    }
}
