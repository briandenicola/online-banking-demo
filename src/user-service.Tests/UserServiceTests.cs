using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using OnlineBankingDemo.Contracts.Dtos;
using UserService.Services;
using Xunit;

namespace UserService.Tests;

public class UserServiceTests
{
    private readonly InMemoryUserService _sut;
    private readonly Mock<ILogger<InMemoryUserService>> _loggerMock;

    public UserServiceTests()
    {
        _loggerMock = new Mock<ILogger<InMemoryUserService>>();
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                { "Demo:Password", "TestPassword123" }
            }!)
            .Build();
        _sut = new InMemoryUserService(_loggerMock.Object, config);
    }

    [Fact]
    public async Task CreateUserAsync_ValidInput_ReturnsUser()
    {
        var request = new RegisterUserRequest
        {
            Username = "newuser",
            Email = "new@example.com",
            Password = "securePass123",
            FirstName = "New",
            LastName = "User"
        };

        var user = await _sut.CreateUserAsync(request);

        user.Should().NotBeNull();
        user.Username.Should().Be("newuser");
        user.Email.Should().Be("new@example.com");
        user.FirstName.Should().Be("New");
        user.LastName.Should().Be("User");
        user.Id.Should().NotBeNullOrEmpty();
        user.PasswordHash.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task CreateUserAsync_DuplicateUsername_ThrowsInvalidOperationException()
    {
        var request = new RegisterUserRequest
        {
            Username = "testuser", // Already seeded in InMemoryUserService
            Email = "another@example.com",
            Password = "securePass123",
            FirstName = "Another",
            LastName = "User"
        };

        var act = () => _sut.CreateUserAsync(request);

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("Username already exists");
    }

    [Fact]
    public async Task ValidateCredentialsAsync_ValidCredentials_ReturnsTrue()
    {
        // "testuser" with configured password "TestPassword123"
        var result = await _sut.ValidateCredentialsAsync("testuser", "TestPassword123");

        result.Should().BeTrue();
    }

    [Fact]
    public async Task ValidateCredentialsAsync_InvalidPassword_ReturnsFalse()
    {
        var result = await _sut.ValidateCredentialsAsync("testuser", "wrongpassword");

        result.Should().BeFalse();
    }

    [Fact]
    public async Task ValidateCredentialsAsync_NonExistentUser_ReturnsFalse()
    {
        var result = await _sut.ValidateCredentialsAsync("nonexistent", "password123");

        result.Should().BeFalse();
    }

    [Fact]
    public async Task GetUserByIdAsync_ExistingUser_ReturnsUser()
    {
        var user = await _sut.GetUserByIdAsync("1");

        user.Should().NotBeNull();
        user!.Username.Should().Be("testuser");
    }

    [Fact]
    public async Task GetUserByIdAsync_NonExistentUser_ReturnsNull()
    {
        var user = await _sut.GetUserByIdAsync("nonexistent-id");

        user.Should().BeNull();
    }

    [Fact]
    public async Task GetUserByUsernameAsync_ExistingUser_ReturnsUser()
    {
        var user = await _sut.GetUserByUsernameAsync("testuser");

        user.Should().NotBeNull();
        user!.Id.Should().Be("1");
    }

    [Fact]
    public async Task GetUserByUsernameAsync_CaseInsensitive_ReturnsUser()
    {
        var user = await _sut.GetUserByUsernameAsync("TESTUSER");

        user.Should().NotBeNull();
        user!.Username.Should().Be("testuser");
    }

    [Fact]
    public async Task GetUserByUsernameAsync_NonExistentUser_ReturnsNull()
    {
        var user = await _sut.GetUserByUsernameAsync("nobody");

        user.Should().BeNull();
    }
}
