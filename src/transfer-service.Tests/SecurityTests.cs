using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using TransferService.Controllers;
using TransferService.Models;
using TransferService.Services;
using System.Security.Claims;
using Xunit;

namespace TransferService.Tests;

[Trait("Category", "Security")]
public class TransfersControllerSecurityTests
{
    private readonly Mock<ITransferService> _transferServiceMock;
    private readonly Mock<ILogger<TransfersController>> _loggerMock;
    private readonly TransfersController _sut;

    public TransfersControllerSecurityTests()
    {
        _transferServiceMock = new Mock<ITransferService>();
        _loggerMock = new Mock<ILogger<TransfersController>>();
        _sut = new TransfersController(_transferServiceMock.Object, _loggerMock.Object);
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
    /// SECURITY: Verifies that InitiateTransfer rejects unauthenticated requests.
    /// Without a valid JWT userId claim, the controller returns Unauthorized.
    /// </summary>
    [Fact]
    public async Task InitiateTransfer_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();
        var request = new CreateTransferRequest
        {
            FromAccountId = "acc-1",
            ToAccountId = "acc-2",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };

        var result = await _sut.InitiateTransfer(request);

        result.Should().BeOfType<UnauthorizedResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetTransfer enforces ownership checks.
    /// When an authenticated user requests a transfer belonging to another user,
    /// the controller returns NotFound to prevent cross-user data access and
    /// information leakage about transfer existence.
    /// </summary>
    [Fact]
    public async Task GetTransfer_OtherUsersTransfer_ReturnsNotFound()
    {
        SetUser("attacker");
        var victimTransfer = new Transfer
        {
            Id = "t-victim",
            UserId = "victim",
            FromAccountId = "acc-v1",
            ToAccountId = "acc-v2",
            FromAccountNumber = "ACC100",
            ToAccountNumber = "ACC200",
            Amount = 10000m,
            Status = "Completed"
        };
        _transferServiceMock
            .Setup(s => s.GetTransferByIdAsync("t-victim"))
            .ReturnsAsync(victimTransfer);

        var result = await _sut.GetTransfer("t-victim");

        result.Should().BeOfType<NotFoundResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that InitiateTransfer correctly passes the JWT-derived userId
    /// to the service layer. The userId is extracted from claims, not from request body
    /// or headers, preventing identity spoofing in transfer initiation.
    /// </summary>
    [Fact]
    public async Task InitiateTransfer_PassesAuthenticatedUserIdToService()
    {
        SetUser("user-1");
        var request = new CreateTransferRequest
        {
            FromAccountId = "acc-1",
            ToAccountId = "acc-2",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 250m,
            Description = "Rent payment"
        };
        var transfer = new Transfer
        {
            Id = "t-1",
            UserId = "user-1",
            FromAccountId = "acc-1",
            ToAccountId = "acc-2",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 250m,
            Status = "Completed"
        };
        _transferServiceMock
            .Setup(s => s.InitiateTransferAsync("user-1", request))
            .ReturnsAsync(transfer);

        var result = await _sut.InitiateTransfer(request);

        result.Should().BeOfType<CreatedAtActionResult>();
        _transferServiceMock.Verify(
            s => s.InitiateTransferAsync("user-1", request), Times.Once);
        // Ensure no other userId was used
        _transferServiceMock.Verify(
            s => s.InitiateTransferAsync(It.Is<string>(id => id != "user-1"), It.IsAny<CreateTransferRequest>()),
            Times.Never);
    }

    /// <summary>
    /// SECURITY: Verifies that a failed transfer returns BadRequest with the failure reason.
    /// When the service marks a transfer as Failed (e.g., insufficient funds, invalid account),
    /// the controller correctly surfaces the error rather than returning success.
    /// </summary>
    [Fact]
    public async Task InitiateTransfer_FailedTransfer_ReturnsBadRequest()
    {
        SetUser("user-1");
        var request = new CreateTransferRequest
        {
            FromAccountId = "acc-1",
            ToAccountId = "acc-2",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 999999m,
            Description = "Large transfer"
        };
        var failedTransfer = new Transfer
        {
            Id = "t-failed",
            UserId = "user-1",
            FromAccountId = "acc-1",
            ToAccountId = "acc-2",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 999999m,
            Status = "Failed",
            FailureReason = "Insufficient funds in source account"
        };
        _transferServiceMock
            .Setup(s => s.InitiateTransferAsync("user-1", request))
            .ReturnsAsync(failedTransfer);

        var result = await _sut.InitiateTransfer(request);

        result.Should().BeOfType<BadRequestObjectResult>();
    }

    /// <summary>
    /// SECURITY: Verifies that GetTransfer requires authentication.
    /// Without a valid JWT userId claim, the controller returns Unauthorized.
    /// </summary>
    [Fact]
    public async Task GetTransfer_NoAuthentication_ReturnsUnauthorized()
    {
        SetNoUser();

        var result = await _sut.GetTransfer("t-1");

        result.Should().BeOfType<UnauthorizedResult>();
    }
}
