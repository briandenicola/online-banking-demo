using FluentAssertions;
using Microsoft.Extensions.Logging;
using Moq;
using AccountService.Services;
using OnlineBankingDemo.Contracts.Dtos;
using Xunit;

namespace AccountService.Tests;

public class AccountServiceTests
{
    private readonly InMemoryAccountService _sut;
    private readonly Mock<ILogger<InMemoryAccountService>> _loggerMock;

    public AccountServiceTests()
    {
        _loggerMock = new Mock<ILogger<InMemoryAccountService>>();
        _sut = new InMemoryAccountService(_loggerMock.Object);
    }

    [Fact]
    public async Task CreateAccountAsync_ValidRequest_ReturnsAccount()
    {
        var request = new CreateAccountRequest
        {
            AccountType = "Checking",
            InitialBalance = 1000m,
            Currency = "USD"
        };

        var account = await _sut.CreateAccountAsync("user-1", request);

        account.Should().NotBeNull();
        account.UserId.Should().Be("user-1");
        account.AccountType.Should().Be("Checking");
        account.Balance.Should().Be(1000m);
        account.Currency.Should().Be("USD");
        account.AccountNumber.Should().StartWith("ACC");
        account.Id.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task CreateAccountAsync_NullCurrency_DefaultsToUSD()
    {
        var request = new CreateAccountRequest
        {
            AccountType = "Savings",
            InitialBalance = 500m,
            Currency = null
        };

        var account = await _sut.CreateAccountAsync("user-1", request);

        account.Currency.Should().Be("USD");
    }

    [Fact]
    public async Task GetAccountByIdAsync_ExistingAccount_ReturnsAccount()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 100m };
        var created = await _sut.CreateAccountAsync("user-1", request);

        var account = await _sut.GetAccountByIdAsync(created.Id);

        account.Should().NotBeNull();
        account!.Id.Should().Be(created.Id);
    }

    [Fact]
    public async Task GetAccountByIdAsync_NonExistentAccount_ReturnsNull()
    {
        var account = await _sut.GetAccountByIdAsync("nonexistent");

        account.Should().BeNull();
    }

    [Fact]
    public async Task GetUserAccountsAsync_ReturnsOnlyUserAccounts()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 100m };
        await _sut.CreateAccountAsync("user-1", request);
        await _sut.CreateAccountAsync("user-1", new CreateAccountRequest { AccountType = "Savings", InitialBalance = 200m });
        await _sut.CreateAccountAsync("user-2", request);

        var accounts = await _sut.GetUserAccountsAsync("user-1");

        accounts.Should().HaveCount(2);
        accounts.Should().AllSatisfy(a => a.UserId.Should().Be("user-1"));
    }

    [Fact]
    public async Task GetAccountByNumberAsync_ExistingAccount_ReturnsAccount()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 100m };
        var created = await _sut.CreateAccountAsync("user-1", request);

        var account = await _sut.GetAccountByNumberAsync(created.AccountNumber);

        account.Should().NotBeNull();
        account!.Id.Should().Be(created.Id);
    }

    [Fact]
    public async Task UpdateBalanceAsync_PositiveAmount_IncreasesBalance()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };
        var created = await _sut.CreateAccountAsync("user-1", request);

        var updated = await _sut.UpdateBalanceAsync(created.Id, 500m);

        updated.Balance.Should().Be(1500m);
    }

    [Fact]
    public async Task UpdateBalanceAsync_NegativeAmount_DecreasesBalance()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };
        var created = await _sut.CreateAccountAsync("user-1", request);

        var updated = await _sut.UpdateBalanceAsync(created.Id, -300m);

        updated.Balance.Should().Be(700m);
    }

    [Fact]
    public async Task UpdateBalanceAsync_ZeroAmount_BalanceUnchanged()
    {
        var request = new CreateAccountRequest { AccountType = "Checking", InitialBalance = 1000m };
        var created = await _sut.CreateAccountAsync("user-1", request);

        var updated = await _sut.UpdateBalanceAsync(created.Id, 0m);

        updated.Balance.Should().Be(1000m);
    }

    [Fact]
    public async Task UpdateBalanceAsync_NonExistentAccount_ThrowsException()
    {
        var act = () => _sut.UpdateBalanceAsync("nonexistent", 100m);

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("Account not found");
    }
}
