using FluentAssertions;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Controllers;
using UserService.Models;
using UserService.Services;
using Xunit;

namespace UserService.Tests;

public class AuthControllerTests
{
    private readonly Mock<IUserService> _userServiceMock;
    private readonly Mock<IAuthService> _authServiceMock;
    private readonly Mock<ILogger<AuthController>> _loggerMock;
    private readonly AuthController _sut;

    public AuthControllerTests()
    {
        _userServiceMock = new Mock<IUserService>();
        _authServiceMock = new Mock<IAuthService>();
        _loggerMock = new Mock<ILogger<AuthController>>();
        _sut = new AuthController(_userServiceMock.Object, _authServiceMock.Object, _loggerMock.Object);
    }

    [Fact]
    public async Task Register_ValidRequest_ReturnsCreated()
    {
        var request = new RegisterUserRequest
        {
            Username = "newuser",
            Email = "new@example.com",
            Password = "securePass123",
            FirstName = "New",
            LastName = "User"
        };
        var user = new User { Id = "123", Username = "newuser" };
        _userServiceMock.Setup(s => s.CreateUserAsync(request)).ReturnsAsync(user);

        var result = await _sut.Register(request);

        result.Should().BeOfType<CreatedAtActionResult>();
    }

    [Fact]
    public async Task Register_DuplicateUser_ReturnsBadRequest()
    {
        var request = new RegisterUserRequest
        {
            Username = "existing",
            Email = "existing@example.com",
            Password = "securePass123",
            FirstName = "Existing",
            LastName = "User"
        };
        _userServiceMock.Setup(s => s.CreateUserAsync(request))
            .ThrowsAsync(new InvalidOperationException("Username already exists"));

        var result = await _sut.Register(request);

        result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task Login_ValidCredentials_ReturnsOkWithToken()
    {
        var request = new LoginRequest { Username = "testuser", Password = "password123" };
        var user = new User { Id = "1", Username = "testuser" };

        _userServiceMock.Setup(s => s.ValidateCredentialsAsync("testuser", "password123"))
            .ReturnsAsync(true);
        _userServiceMock.Setup(s => s.GetUserByUsernameAsync("testuser"))
            .ReturnsAsync(user);
        _authServiceMock.Setup(s => s.GenerateTokenAsync("1", "testuser", "user"))
            .ReturnsAsync("jwt-token-here");

        var result = await _sut.Login(request);

        result.Should().BeOfType<OkObjectResult>();
    }

    [Fact]
    public async Task Login_InvalidCredentials_ReturnsUnauthorized()
    {
        var request = new LoginRequest { Username = "testuser", Password = "wrongpassword" };
        _userServiceMock.Setup(s => s.ValidateCredentialsAsync("testuser", "wrongpassword"))
            .ReturnsAsync(false);

        var result = await _sut.Login(request);

        result.Should().BeOfType<UnauthorizedObjectResult>();
    }

    [Fact]
    public async Task Login_NonExistentUser_ReturnsUnauthorized()
    {
        var request = new LoginRequest { Username = "nobody", Password = "password123" };
        _userServiceMock.Setup(s => s.ValidateCredentialsAsync("nobody", "password123"))
            .ReturnsAsync(false);

        var result = await _sut.Login(request);

        result.Should().BeOfType<UnauthorizedObjectResult>();
    }
}
