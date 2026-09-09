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

public class AccountsControllerTests
{
    private readonly Mock<IAccountService> _accountServiceMock;
    private readonly Mock<ILogger<AccountsController>> _loggerMock;
    private readonly AccountsController _sut;

    public AccountsControllerTests()
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

    [Fact]
    public async Task CreateAccount_WithAuthenticatedUser_ReturnsOk()
    {
        SetUser("user-1");
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };
        var account = new Account
        {
            Id = "acc-1",
            UserId = "user-1",
            AccountNumber = "ACC12345678",
            AccountType = "Checking",
            Balance = 1000m,
            Currency = "USD"
        };
        _accountServiceMock.Setup(s => s.CreateAccountAsync("user-1", request)).ReturnsAsync(account);

        var result = await _sut.CreateAccount(request);

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task CreateAccount_WithoutAuth_ReturnsUnauthorized()
    {
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext()
        };
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };

        var result = await _sut.CreateAccount(request);

        result.Should().BeOfType<UnauthorizedResult>();
    }

    [Fact]
    public async Task GetUserAccounts_ReturnsUserAccounts()
    {
        SetUser("user-1");
        var accounts = new List<Account>
        {
            new() { Id = "1", UserId = "user-1", AccountNumber = "ACC001", AccountType = "Checking", Balance = 500m },
            new() { Id = "2", UserId = "user-1", AccountNumber = "ACC002", AccountType = "Savings", Balance = 1000m }
        };
        _accountServiceMock.Setup(s => s.GetUserAccountsAsync("user-1")).ReturnsAsync(accounts);

        var result = await _sut.GetUserAccounts();

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task GetAccount_OwnedAccount_ReturnsOk()
    {
        SetUser("user-1");
        var account = new Account { Id = "acc-1", UserId = "user-1", AccountNumber = "ACC001" };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);

        var result = await _sut.GetAccount("acc-1");

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task GetAccount_NotOwnedAccount_ReturnsForbidden()
    {
        SetUser("user-1");
        var account = new Account { Id = "acc-1", UserId = "user-2", AccountNumber = "ACC001" };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);

        var result = await _sut.GetAccount("acc-1");

        // §B2: FORBIDDEN, which is a different fact from ABSENT and now says so.
        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    [Fact]
    public async Task GetAccount_NonExistent_ReturnsNotFound()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("nonexistent")).ReturnsAsync((Account?)null);

        var result = await _sut.GetAccount("nonexistent");

        result.Should().BeOfType<NotFoundResult>();
    }

    [Fact]
    public async Task UpdateBalance_ValidRequest_ReturnsOk()
    {
        SetUser("user-1");
        var account = new Account { Id = "acc-1", UserId = "user-1", Balance = 1500m };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);
        _accountServiceMock.Setup(s => s.UpdateBalanceAsync("acc-1", 500m)).ReturnsAsync(account);

        var result = await _sut.UpdateBalance("acc-1", new UpdateBalanceRequest { Amount = 500m });

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task UpdateBalance_NonExistentAccount_ReturnsNotFound()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("nonexistent")).ReturnsAsync((Account?)null);

        var result = await _sut.UpdateBalance("nonexistent", new UpdateBalanceRequest { Amount = 100m });

        result.Should().BeOfType<NotFoundResult>();
    }

    // ---------------------------------------------------------------- ruling §B1/§B2/§B4.3 ----
    //
    // Three facts, three answers, one test per row of the §B2 table, per endpoint. The rows are
    // asserted through the CONTROLLER rather than through a fixture that hands back a status:
    // the thing under test is that the endpoint PRODUCES the answer, and a test that supplies it
    // would pass with the whole check deleted.

    private void SetUserWithRoles(string userId, params string[] roles)
    {
        var claims = new List<Claim> { new("userId", userId) };
        claims.AddRange(roles.Select(r => new Claim(ClaimTypes.Role, r)));
        var identity = new ClaimsIdentity(claims, "Test");
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext { User = new ClaimsPrincipal(identity) }
        };
    }

    private Account CustomerAccount() =>
        new() { Id = "acc-casey", UserId = "casey", AccountNumber = "ACC777", Balance = 4200m };

    [Theory]
    [InlineData("banker")]
    [InlineData("supervisor")]
    public async Task GetAccount_AsBankingAuthority_ReadsACustomersAccount(string role)
    {
        // THE POINT OF THE HARNESS: a banker works a customer's case. Before this, the only
        // accounts the evidence tools could read were the banker's OWN, which is why the seeder
        // had to give the banker accounts and why the demo showed a banker adjusting his own
        // balance.
        SetUserWithRoles("banker-1", role);
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-casey")).ReturnsAsync(CustomerAccount());

        var result = await _sut.GetAccount("acc-casey");

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task GetAccount_AsAdmin_IsForbidden()
    {
        // §B1.1 and §5.8.2: admin implies NEITHER banker nor supervisor. Platform authority is
        // not banking authority, and reading a customer's money is banking. This is the reason
        // CustomerFinancialRead exists as a new constant instead of reusing IdentityRead, which
        // carries Admin for a platform reason that does not apply here.
        SetUserWithRoles("admin-1", "admin", "Admin");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-casey")).ReturnsAsync(CustomerAccount());

        var result = await _sut.GetAccount("acc-casey");

        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    [Fact]
    public async Task GetAccount_AbsentAccount_StillReturnsNotFound_EvenForABanker()
    {
        // ABSENT keeps 404, for everyone. This row is what makes `count: 0` from
        // list_account_transactions safe to read: get_account answers existence, and its 404
        // leaves the evidence key absent so EvidenceComplete fails (§B3.1).
        SetUserWithRoles("banker-1", "banker");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("no-such")).ReturnsAsync((Account?)null);

        var result = await _sut.GetAccount("no-such");

        result.Should().BeOfType<NotFoundResult>();
    }

    [Theory]
    [InlineData("banker")]
    [InlineData("supervisor")]
    public async Task GetAccountByNumber_AsBankingAuthority_ReadsACustomersAccount(string role)
    {
        SetUserWithRoles("banker-1", role);
        _accountServiceMock.Setup(s => s.GetAccountByNumberAsync("ACC777")).ReturnsAsync(CustomerAccount());

        var result = await _sut.GetAccountByNumber("ACC777");

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task GetAccountByNumber_AsAdmin_IsForbidden()
    {
        SetUserWithRoles("admin-1", "admin");
        _accountServiceMock.Setup(s => s.GetAccountByNumberAsync("ACC777")).ReturnsAsync(CustomerAccount());

        var result = await _sut.GetAccountByNumber("ACC777");

        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
    }

    [Theory]
    [InlineData("banker")]
    [InlineData("supervisor")]
    public async Task UpdateBalance_AsBankingAuthority_AdjustsACustomersAccount(string role)
    {
        // §B4.3, and this is the step Brian hits ten minutes after the read fix if it is missed:
        // evidence gathered, proposal made, approval signed — and then a 404 on execution. The
        // demo would fail one step LATER, which is worse, because by then it looks like the
        // harness worked.
        SetUserWithRoles("banker-1", role);
        var account = CustomerAccount();
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-casey")).ReturnsAsync(account);
        _accountServiceMock.Setup(s => s.UpdateBalanceAsync("acc-casey", -250m)).ReturnsAsync(account);

        var result = await _sut.UpdateBalance("acc-casey", new UpdateBalanceRequest { Amount = -250m });

        result.Should().BeOfType<OkObjectResult>();
        _accountServiceMock.Verify(s => s.UpdateBalanceAsync("acc-casey", -250m), Times.Once);
    }

    [Fact]
    public async Task UpdateBalance_AsAdmin_IsForbiddenAndDoesNotWrite()
    {
        SetUserWithRoles("admin-1", "admin");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-casey")).ReturnsAsync(CustomerAccount());

        var result = await _sut.UpdateBalance("acc-casey", new UpdateBalanceRequest { Amount = -250m });

        result.Should().BeOfType<ObjectResult>()
            .Which.StatusCode.Should().Be(StatusCodes.Status403Forbidden);
        _accountServiceMock.Verify(
            s => s.UpdateBalanceAsync(It.IsAny<string>(), It.IsAny<decimal>()),
            Times.Never,
            "a denied write must not reach the service at all");
    }

    [Fact]
    public async Task UpdateBalance_AbsentAccount_ReturnsNotFound_NotForbidden()
    {
        // The write side keeps the three facts apart too: nothing to write to is not the same
        // fact as not being allowed to write.
        SetUserWithRoles("banker-1", "banker");
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("no-such")).ReturnsAsync((Account?)null);

        var result = await _sut.UpdateBalance("no-such", new UpdateBalanceRequest { Amount = 1m });

        result.Should().BeOfType<NotFoundResult>();
    }

    [Fact]
    public async Task CustomerFinancialRead_DoesNotGrantAdmin_AndIsSeparateFromIdentityRead()
    {
        // The constants themselves, asserted rather than trusted. A later edit that "tidied" the
        // two lists into one would make admin a customer-financial reader in one keystroke, and
        // every behavioural test above would still pass if the members were also copied.
        Banking.Auth.BankingRoles.CustomerFinancialRead.Should().NotContain("admin");
        Banking.Auth.BankingRoles.CustomerFinancialRead.Should().NotContain("Admin");
        Banking.Auth.BankingRoles.CustomerFinancialWrite.Should().NotContain("admin");
        Banking.Auth.BankingRoles.CustomerFinancialWrite.Should().NotContain("Admin");
        Banking.Auth.BankingRoles.CustomerFinancialRead.Should().NotBe(Banking.Auth.BankingRoles.IdentityRead);
    }
}
