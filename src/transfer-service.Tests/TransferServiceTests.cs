using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using TransferService.Services;
using Xunit;

namespace TransferService.Tests;

public class TransferServiceTests
{
    private readonly InMemoryTransferService _sut;

    public TransferServiceTests()
    {
        _sut = new InMemoryTransferService(
            Mock.Of<IConnectionMultiplexer>(),
            Mock.Of<IHttpClientFactory>(),
            Mock.Of<IHttpContextAccessor>(),
            Mock.Of<IConfiguration>(),
            Mock.Of<ILogger<InMemoryTransferService>>());
    }

    [Fact]
    public async Task InitiateTransferAsync_ValidRequest_ReturnsTransfer()
    {
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m,
            Description = "Test transfer"
        };

        var transfer = await _sut.InitiateTransferAsync("user-1", request);

        transfer.Should().NotBeNull();
        transfer.FromAccountNumber.Should().Be("ACC001");
        transfer.ToAccountNumber.Should().Be("ACC002");
        transfer.Amount.Should().Be(100m);
        transfer.Description.Should().Be("Test transfer");
        transfer.Status.Should().Be("Pending");
        transfer.Id.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task InitiateTransferAsync_SetsInitiatedTimestamp()
    {
        var before = DateTime.UtcNow;
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 50m
        };

        var transfer = await _sut.InitiateTransferAsync("user-1", request);

        transfer.InitiatedAt.Should().BeOnOrAfter(before);
        transfer.InitiatedAt.Should().BeOnOrBefore(DateTime.UtcNow);
    }

    [Fact]
    public async Task InitiateTransferAsync_SelfTransfer_CreatesTransfer()
    {
        // Current implementation doesn't reject self-transfers; documenting behavior
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC001",
            Amount = 100m
        };

        var transfer = await _sut.InitiateTransferAsync("user-1", request);

        transfer.Should().NotBeNull();
        transfer.FromAccountNumber.Should().Be(transfer.ToAccountNumber);
    }

    [Fact]
    public async Task GetTransferByIdAsync_ExistingTransfer_ReturnsTransfer()
    {
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };
        var created = await _sut.InitiateTransferAsync("user-1", request);

        var transfer = await _sut.GetTransferByIdAsync(created.Id);

        transfer.Should().NotBeNull();
        transfer!.Id.Should().Be(created.Id);
        transfer.Amount.Should().Be(100m);
    }

    [Fact]
    public async Task GetTransferByIdAsync_NonExistentTransfer_ReturnsNull()
    {
        var transfer = await _sut.GetTransferByIdAsync("nonexistent");

        transfer.Should().BeNull();
    }

    [Fact]
    public async Task InitiateTransferAsync_MultipleTransfers_AllStored()
    {
        var request1 = new CreateTransferRequest { FromAccountNumber = "ACC001", ToAccountNumber = "ACC002", Amount = 100m };
        var request2 = new CreateTransferRequest { FromAccountNumber = "ACC001", ToAccountNumber = "ACC003", Amount = 200m };
        var request3 = new CreateTransferRequest { FromAccountNumber = "ACC002", ToAccountNumber = "ACC001", Amount = 50m };

        var t1 = await _sut.InitiateTransferAsync("user-1", request1);
        var t2 = await _sut.InitiateTransferAsync("user-1", request2);
        var t3 = await _sut.InitiateTransferAsync("user-2", request3);

        (await _sut.GetTransferByIdAsync(t1.Id)).Should().NotBeNull();
        (await _sut.GetTransferByIdAsync(t2.Id)).Should().NotBeNull();
        (await _sut.GetTransferByIdAsync(t3.Id)).Should().NotBeNull();
    }
}
