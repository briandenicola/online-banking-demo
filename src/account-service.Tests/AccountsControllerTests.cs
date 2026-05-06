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
    public async Task GetAccount_NotOwnedAccount_ReturnsForbid()
    {
        SetUser("user-1");
        var account = new Account { Id = "acc-1", UserId = "user-2", AccountNumber = "ACC001" };
        _accountServiceMock.Setup(s => s.GetAccountByIdAsync("acc-1")).ReturnsAsync(account);

        var result = await _sut.GetAccount("acc-1");

        result.Should().BeOfType<ForbidResult>();
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
        var account = new Account { Id = "acc-1", Balance = 1500m };
        _accountServiceMock.Setup(s => s.UpdateBalanceAsync("acc-1", 500m)).ReturnsAsync(account);

        var result = await _sut.UpdateBalance("acc-1", new UpdateBalanceRequest { Amount = 500m });

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task UpdateBalance_NonExistentAccount_ReturnsBadRequest()
    {
        SetUser("user-1");
        _accountServiceMock.Setup(s => s.UpdateBalanceAsync("nonexistent", 100m))
            .ThrowsAsync(new InvalidOperationException("Account not found"));

        var result = await _sut.UpdateBalance("nonexistent", new UpdateBalanceRequest { Amount = 100m });

        result.Should().BeOfType<BadRequestObjectResult>();
    }
}
