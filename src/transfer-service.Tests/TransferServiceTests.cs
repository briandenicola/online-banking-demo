using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using StackExchange.Redis;
using System.Net;
using System.Text;
using TransferService.Services;
using Xunit;

namespace TransferService.Tests;

public class TransferServiceTests
{
    private const string OwnerUserId = "user-1";

    private readonly InMemoryTransferService _sut;

    // Mock.Of<IConnectionMultiplexer>() returns null from GetDatabase(), and the
    // service publishes a transfer event on every write path, so tests died on a
    // null dereference inside StreamAddAsync rather than on anything they were
    // written to check. Give the multiplexer a database that records nothing.
    private static IConnectionMultiplexer StubRedis()
    {
        var database = new Mock<IDatabase>();
        database
            .Setup(d => d.StreamAddAsync(
                It.IsAny<RedisKey>(),
                It.IsAny<NameValueEntry[]>(),
                It.IsAny<RedisValue?>(),
                It.IsAny<int?>(),
                It.IsAny<bool>(),
                It.IsAny<CommandFlags>()))
            .ReturnsAsync(new RedisValue("0-1"));

        var multiplexer = new Mock<IConnectionMultiplexer>();
        multiplexer
            .Setup(m => m.GetDatabase(It.IsAny<int>(), It.IsAny<object>()))
            .Returns(database.Object);

        return multiplexer.Object;
    }

    // The transfer flow makes two different kinds of call: a GET to
    // account-service to verify ownership, then two POSTs to transaction-service
    // for the debit and the credit legs. Answering by method keeps one stub
    // honest for the whole flow without pretending a POST is an account lookup.
    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly HttpStatusCode _ownershipStatus;
        private readonly Func<string, string> _ownerOf;

        public StubHandler(HttpStatusCode ownershipStatus, Func<string, string> ownerOf)
        {
            _ownershipStatus = ownershipStatus;
            _ownerOf = ownerOf;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Get)
            {
                var accountId = request.RequestUri!.Segments[^1].TrimEnd('/');
                var body = $"{{\"id\":\"{accountId}\",\"userId\":\"{_ownerOf(accountId)}\"}}";
                return Task.FromResult(new HttpResponseMessage(_ownershipStatus)
                {
                    Content = new StringContent(body, Encoding.UTF8, "application/json")
                });
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Created)
            {
                Content = new StringContent("{\"id\":\"txn-1\"}", Encoding.UTF8, "application/json")
            });
        }
    }

    // Ownership is per account, not global: answering "user-1 owns everything"
    // would make an ownership check impossible to fail and the tests below
    // vacuous. ACC002 belongs to user-2 so that a cross-user transfer in these
    // fixtures is a real one.
    private static readonly Dictionary<string, string> AccountOwners = new()
    {
        ["ACC001"] = OwnerUserId,
        ["ACC002"] = "user-2",
        ["ACC003"] = OwnerUserId
    };

    // The service verifies account ownership against account-service before
    // moving money, and throws when it cannot. That is correct — it fails closed
    // — but it means these tests need both a configured URL and an
    // account-service that answers, or every write path throws before reaching
    // the behaviour under test.
    private static IHttpClientFactory StubAccountService(
        string? forceOwner = null, HttpStatusCode status = HttpStatusCode.OK)
    {
        Func<string, string> ownerOf = forceOwner is not null
            ? _ => forceOwner
            : id => AccountOwners.TryGetValue(id, out var owner) ? owner : OwnerUserId;

        var factory = new Mock<IHttpClientFactory>();
        factory
            .Setup(f => f.CreateClient(It.IsAny<string>()))
            .Returns(() => new HttpClient(new StubHandler(status, ownerOf)));
        return factory.Object;
    }

    private static IConfiguration ConfigWithAccountService(string? url = "http://account-service") =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Services:AccountService"] = url,
                ["Services:TransactionService"] = "http://transaction-service"
            })
            .Build();

    private static InMemoryTransferService BuildSut(
        IHttpClientFactory? accountService = null,
        IConfiguration? configuration = null) =>
        new(
            StubRedis(),
            accountService ?? StubAccountService(),
            Mock.Of<IHttpContextAccessor>(),
            configuration ?? ConfigWithAccountService(),
            Mock.Of<ILogger<InMemoryTransferService>>());

    public TransferServiceTests()
    {
        _sut = BuildSut();
    }

    // Nothing asserted the fail-closed behaviour itself, so a change that made
    // an unreachable account-service mean "ownership is fine" would not have
    // been caught by any test in this suite.
    [Fact]
    public async Task InitiateTransferAsync_AccountServiceNotConfigured_Throws()
    {
        var sut = BuildSut(configuration: ConfigWithAccountService(null));
        var request = new CreateTransferRequest
        {
            FromAccountId = "ACC001",
            ToAccountId = "ACC002",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };

        var act = async () => await sut.InitiateTransferAsync(OwnerUserId, request);

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("*cannot verify account ownership*");
    }

    [Fact]
    public async Task InitiateTransferAsync_AccountOwnedByAnotherUser_Throws()
    {
        var sut = BuildSut(accountService: StubAccountService("someone-else"));
        var request = new CreateTransferRequest
        {
            FromAccountId = "ACC001",
            ToAccountId = "ACC002",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };

        var act = async () => await sut.InitiateTransferAsync(OwnerUserId, request);

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("*not found or not accessible*");
    }

    [Fact]
    public async Task InitiateTransferAsync_ValidRequest_ReturnsTransfer()
    {
        var request = new CreateTransferRequest
        {
            FromAccountId = "ACC001",
            ToAccountId = "ACC002",
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
        // Was "Pending". A completed transfer has been "Completed" since the
        // executor started performing the debit and credit legs inline; the old
        // assertion encoded a status this service no longer produces on success.
        transfer.Status.Should().Be("Completed");
        transfer.Id.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task InitiateTransferAsync_SetsInitiatedTimestamp()
    {
        var before = DateTime.UtcNow;
        var request = new CreateTransferRequest
        {
            FromAccountId = "ACC001",
            ToAccountId = "ACC002",
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
            FromAccountId = "ACC001",
            ToAccountId = "ACC001",
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
            FromAccountId = "ACC001",
            ToAccountId = "ACC002",
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
        var request1 = new CreateTransferRequest { FromAccountId = "ACC001", ToAccountId = "ACC002", FromAccountNumber = "ACC001", ToAccountNumber = "ACC002", Amount = 100m };
        var request2 = new CreateTransferRequest { FromAccountId = "ACC001", ToAccountId = "ACC003", FromAccountNumber = "ACC001", ToAccountNumber = "ACC003", Amount = 200m };
        var request3 = new CreateTransferRequest { FromAccountId = "ACC002", ToAccountId = "ACC001", FromAccountNumber = "ACC002", ToAccountNumber = "ACC001", Amount = 50m };

        var t1 = await _sut.InitiateTransferAsync("user-1", request1);
        var t2 = await _sut.InitiateTransferAsync("user-1", request2);
        var t3 = await _sut.InitiateTransferAsync("user-2", request3);

        (await _sut.GetTransferByIdAsync(t1.Id)).Should().NotBeNull();
        (await _sut.GetTransferByIdAsync(t2.Id)).Should().NotBeNull();
        (await _sut.GetTransferByIdAsync(t3.Id)).Should().NotBeNull();
    }
}
