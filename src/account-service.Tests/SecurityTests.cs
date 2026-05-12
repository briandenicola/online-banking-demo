using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using AccountService.Controllers;
using AccountService.Models;
using AccountService.Services;
using OnlineBankingDemo.Contracts.Dtos;
using System.Security.Claims;
using Xunit;

namespace AccountService.Tests;

[Trait("Category", "Security")]
public class AccountsControllerSecurityTests
{
    private readonly Mock<IAccountService> _accountServiceMock;
    private readonly Mock<ILogger<AccountsController>> _loggerMock;
    private readonly AccountsController _sut;

    public AccountsControllerSecurityTests()
    {
        _accountServiceMock = new Mock<IAccountService>();
        _loggerMock = new Mock<ILogger<AccountsController>>();
        _sut = new AccountsController(_accountServiceMock.Object, _loggerMock.Object);
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
    /// SECURITY: Verifies that CreateAccount rejects requests without a valid JWT userId claim.
    /// The controller correctly returns Unauthorized when no identity is present,
    /// preventing unauthenticated account creation.
    /// </summary>
    [Fact]
    public async Task CreateAccount_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };

        var result = await _sut.CreateAccount(request);

        result.Should().BeOfType<UnauthorizedResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that the controller extracts userId exclusively from JWT claims
    /// and does not fall back to any header-based identity (e.g., X-User-Id).
    /// An unauthenticated request with a spoofed X-User-Id header must be rejected.
    /// </summary>
    [Fact]
    public async Task CreateAccount_XUserIdHeader_IsIgnored_NoFallback()
    {
        // Setup: no JWT claims, but set X-User-Id header to simulate spoofing attempt
        var httpContext = new DefaultHttpContext();
        httpContext.Request.Headers["X-User-Id"] = "spoofed-user";
        _sut.ControllerContext = new ControllerContext { HttpContext = httpContext };

        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 500m };

        var result = await _sut.CreateAccount(request);

        // The controller correctly ignores X-User-Id header and returns Unauthorized
        result.Should().BeOfType<UnauthorizedResult>();
        _accountServiceMock.Verify(
            s => s.CreateAccountAsync(It.IsAny<string>(), It.IsAny<CreateAccountRequest>()),
            Times.Never,
            "Account should not be created when identity comes only from a header");
    }

    /// <summary>
    /// SECURITY: Verifies that GetAccount denies access to accounts owned by other users.
    /// The controller returns NotFound (rather than Forbid) to avoid leaking information
    /// about the existence of other users' accounts.
    /// </summary>
    [Fact]
    public async Task GetAccount_OtherUsersAccount_ReturnsNotFound()
    {
        SetUser("attacker");
        var victimAccount = new Account
        {
            Id = "acc-victim",
            UserId = "victim",
            AccountNumber = "ACC999",
            AccountType = "Checking",
            Balance = 50000m
        };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-victim")).ReturnsAsync(victimAccount);

        var result = await _sut.GetAccount("acc-victim");

        // Returns NotFound to prevent account enumeration attacks
        result.Should().BeOfType<NotFoundResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetAccount requires authentication.
    /// Without a valid JWT userId claim, the request is rejected.
    /// </summary>
    [Fact]
    public async Task GetAccount_NoAuthentication_ReturnsNotFound()
    {
        SetNoUser();
        var account = new Account
        {
            Id = "acc-1",
            UserId = "user-1",
            AccountNumber = "ACC001",
            AccountType = "Checking",
            Balance = 1000m
        };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);

        var result = await _sut.GetAccount("acc-1");

        // Controller checks userId claim is not empty; returns NotFound when missing
        result.Should().BeOfType<NotFoundResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetAccountByNumber enforces ownership checks.
    /// An authenticated user cannot look up another user's account by account number.
    /// The controller returns NotFound to prevent information disclosure.
    /// </summary>
    [Fact]
    public async Task GetAccountByNumber_OtherUsersAccount_ReturnsNotFound()
    {
        SetUser("attacker");
        var victimAccount = new Account
        {
            Id = "acc-victim",
            UserId = "victim",
            AccountNumber = "ACC999",
            AccountType = "Savings",
            Balance = 100000m
        };
        _accountServiceMock.Setup(s => s.GetAccountByNumberAsync("ACC999")).ReturnsAsync(victimAccount);

        var result = await _sut.GetAccountByNumber("ACC999");

        result.Should().BeOfType<NotFoundResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that UpdateBalance enforces ownership checks.
    /// An authenticated user cannot modify another user's account balance.
    /// The controller returns NotFound to prevent unauthorized balance manipulation.
    /// </summary>
    [Fact]
    public async Task UpdateBalance_OtherUsersAccount_ReturnsNotFound()
    {
        SetUser("attacker");
        var victimAccount = new Account
        {
            Id = "acc-victim",
            UserId = "victim",
            AccountNumber = "ACC999",
            AccountType = "Checking",
            Balance = 50000m
        };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-victim")).ReturnsAsync(victimAccount);

        var result = await _sut.UpdateBalance("acc-victim", new UpdateBalanceRequest { Amount = -50000m });

        result.Should().BeOfType<NotFoundResult>();
        _accountServiceMock.Verify(
            s => s.UpdateBalanceAsync(It.IsAny<string>(), It.IsAny<decimal>()),
            Times.Never,
            "Balance update should not proceed for accounts not owned by the caller");
    }

    /// <summary>
    /// SECURITY: Verifies that GetUserAccounts extracts userId from JWT and only
    /// returns accounts belonging to the authenticated user. The service layer is
    /// called with the correct userId, preventing cross-user data access.
    /// </summary>
    [Fact]
    public async Task GetUserAccounts_OnlyReturnsOwnAccounts()
    {
        SetUser("user-1");
        var ownAccounts = new List<Account>
        {
            new() { Id = "acc-1", UserId = "user-1", AccountNumber = "ACC001", AccountType = "Checking", Balance = 500m }
        };
        _accountServiceMock.Setup(s => s.GetUserAccountsAsync("user-1")).ReturnsAsync(ownAccounts);

        var result = await _sut.GetUserAccounts();

        result.Should().BeOfType<OkObjectResult>();
        _accountServiceMock.Verify(s => s.GetUserAccountsAsync("user-1"), Times.Once);
        // Ensure it was NOT called with any other userId
        _accountServiceMock.Verify(
            s => s.GetUserAccountsAsync(It.Is<string>(id => id != "user-1")),
            Times.Never);
    }

    /// <summary>
    /// SECURITY: Verifies that GetUserAccounts requires authentication.
    /// Without a valid JWT userId claim, the request is rejected with Unauthorized.
    /// </summary>
    [Fact]
    public async Task GetUserAccounts_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();

        var result = await _sut.GetUserAccounts();

        result.Should().BeOfType<UnauthorizedResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that UpdateBalance requires authentication.
    /// Without a valid JWT userId claim, the request is rejected with Unauthorized.
    /// </summary>
    [Fact]
    public async Task UpdateBalance_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();

        var result = await _sut.UpdateBalance("acc-1", new UpdateBalanceRequest { Amount = 1000m });

        result.Should().BeOfType<UnauthorizedResult>();
    }
}

/// <summary>
/// Security tests for Issue #37: Exception Leaking Stopped.
/// Verifies controllers return generic errors with correlation IDs instead of raw exceptions.
/// </summary>
[Trait("Category", "Security")]
[Trait("Issue", "37")]
public class ExceptionLeakingTests
{
    private readonly Mock<IAccountService> _accountServiceMock;
    private readonly Mock<ILogger<AccountsController>> _loggerMock;
    private readonly AccountsController _sut;

    public ExceptionLeakingTests()
    {
        _accountServiceMock = new Mock<IAccountService>();
        _loggerMock = new Mock<ILogger<AccountsController>>();
        _sut = new AccountsController(_accountServiceMock.Object, _loggerMock.Object);
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
    /// SECURITY (Issue #37): Verify exceptions return generic error + correlationId.
    /// Controller should catch exceptions and return { error, correlationId } format,
    /// NOT raw exception messages or stack traces.
    /// </summary>
    [Fact]
    public async Task CreateAccount_ServiceException_ReturnsGenericError()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.CreateAccountAsync(It.IsAny<string>(), It.IsAny<CreateAccountRequest>()))
            .ThrowsAsync(new Exception("Internal database connection failed: [ConnectionString=Server=...;Password=secret123]"));

        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };
        var result = await _sut.CreateAccount(request);

        // Should return error response, not expose exception details
        result.Should().BeOfType<ObjectResult>();
        var objResult = result as ObjectResult;
        objResult!.StatusCode.Should().Be(500);

        // Verify response structure
        var value = objResult.Value;
        value.Should().NotBeNull();

        // Response should have 'error' field
        var errorProp = value!.GetType().GetProperty("error");
        errorProp.Should().NotBeNull("Response should have 'error' property");
        var errorMsg = errorProp!.GetValue(value)?.ToString();
        errorMsg.Should().NotBeNullOrEmpty();

        // Should NOT contain sensitive exception details
        errorMsg!.Should().NotContain("ConnectionString", "Should not leak connection strings");
        errorMsg.Should().NotContain("Password=", "Should not leak passwords");
        errorMsg.Should().NotContain("secret123", "Should not leak secrets");
        errorMsg.Should().NotContain("at AccountService", "Should not leak stack traces");
        errorMsg.Should().NotContain(".cs:line", "Should not leak file paths");

        // Response should have 'correlationId' field
        var corrIdProp = value.GetType().GetProperty("correlationId");
        corrIdProp.Should().NotBeNull("Response should have 'correlationId' for tracking");
    }

    /// <summary>
    /// SECURITY (Issue #37): Verify business exceptions return safe messages.
    /// Business exceptions (like InsufficientFunds) should return user-friendly messages,
    /// not raw exception text.
    /// </summary>
    [Fact]
    public async Task UpdateBalance_InsufficientFunds_ReturnsSafeMessage()
    {
        SetUser("user-1");
        var account = new Account
        {
            Id = "acc-1",
            UserId = "user-1",
            Balance = 100m,
            AccountType = "Checking"
        };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);
        _accountServiceMock.Setup(s => s.UpdateBalanceAsync("acc-1", -200m))
            .ThrowsAsync(new InvalidOperationException("Insufficient funds: cannot withdraw 200 from balance 100"));

        var result = await _sut.UpdateBalance("acc-1", new UpdateBalanceRequest { Amount = -200m });

        // Should return BadRequest or similar with safe message
        result.Should().BeOfType<BadRequestObjectResult>();
        var badReq = result as BadRequestObjectResult;
        var value = badReq!.Value;

        // Check for safe error message
        var errorProp = value!.GetType().GetProperty("error");
        errorProp.Should().NotBeNull();
        var errorMsg = errorProp!.GetValue(value)?.ToString();

        // Should contain safe business message
        errorMsg.Should().Contain("Insufficient funds");

        // Should NOT contain raw exception formatting
        errorMsg.Should().NotContain("System.InvalidOperationException", "Should not leak exception type");
    }

    /// <summary>
    /// SECURITY (Issue #37): Verify correlation ID is present in error responses.
    /// All error responses should include correlation ID for debugging.
    /// </summary>
    [Fact]
    public async Task GetAccount_ServiceException_IncludesCorrelationId()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync(It.IsAny<string>()))
            .ThrowsAsync(new Exception("Cosmos DB timeout after 30 seconds"));

        var result = await _sut.GetAccount("acc-1");

        result.Should().BeOfType<ObjectResult>();
        var objResult = result as ObjectResult;
        var value = objResult!.Value;

        // Verify correlationId field exists
        var corrIdProp = value!.GetType().GetProperty("correlationId");
        corrIdProp.Should().NotBeNull("Error response must include correlationId");

        var corrId = corrIdProp!.GetValue(value)?.ToString();
        corrId.Should().NotBeNullOrEmpty("CorrelationId should have a value");
    }

    /// <summary>
    /// SECURITY (Issue #37): Verify error messages are generic, not specific.
    /// Generic errors prevent information leakage about system internals.
    /// </summary>
    [Fact]
    public async Task GetUserAccounts_Exception_ReturnsGenericMessage()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.GetUserAccountsAsync("user-1"))
            .ThrowsAsync(new Exception("Redis cluster node 10.0.5.23:6379 unreachable"));

        var result = await _sut.GetUserAccounts();

        result.Should().BeOfType<ObjectResult>();
        var objResult = result as ObjectResult;
        var value = objResult!.Value;

        var errorProp = value!.GetType().GetProperty("error");
        var errorMsg = errorProp!.GetValue(value)?.ToString();

        // Should NOT leak internal IP addresses
        errorMsg.Should().NotContain("10.0.5.23", "Should not leak internal IPs");
        errorMsg.Should().NotContain("6379", "Should not leak port numbers");

        // Should be generic
        errorMsg.Should().NotContain("Redis", "Should use generic error message");
    }
}
