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

public class TransfersControllerTests
{
    private readonly Mock<ITransferService> _transferServiceMock;
    private readonly Mock<ILogger<TransfersController>> _loggerMock;
    private readonly TransfersController _sut;

    public TransfersControllerTests()
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

    [Fact]
    public async Task InitiateTransfer_AuthenticatedUser_ReturnsCreated()
    {
        SetUser("user-1");
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m,
            Description = "Payment"
        };
        var transfer = new Transfer
        {
            Id = "t-1",
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };
        _transferServiceMock.Setup(s => s.InitiateTransferAsync("user-1", request)).ReturnsAsync(transfer);

        var result = await _sut.InitiateTransfer(request);

        result.Should().BeOfType<CreatedAtActionResult>();
    }

    [Fact]
    public async Task InitiateTransfer_NoAuth_ReturnsUnauthorized()
    {
        _sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext()
        };
        var request = new CreateTransferRequest
        {
            FromAccountNumber = "ACC001",
            ToAccountNumber = "ACC002",
            Amount = 100m
        };

        var result = await _sut.InitiateTransfer(request);

        result.Should().BeOfType<UnauthorizedResult>();
    }

    [Fact]
    public async Task GetTransfer_ExistingTransfer_ReturnsOk()
    {
        var transfer = new Transfer { Id = "t-1", Amount = 100m };
        _transferServiceMock.Setup(s => s.GetTransferByIdAsync("t-1")).ReturnsAsync(transfer);

        var result = await _sut.GetTransfer("t-1");

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task GetTransfer_NonExistentTransfer_ReturnsNotFound()
    {
        _transferServiceMock.Setup(s => s.GetTransferByIdAsync("nonexistent")).ReturnsAsync((Transfer?)null);

        var result = await _sut.GetTransfer("nonexistent");

        result.Should().BeOfType<NotFoundResult>();
    }
}
