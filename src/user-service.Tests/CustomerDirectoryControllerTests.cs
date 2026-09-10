using Banking.Auth;
using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using UserService.Controllers;
using UserService.Models;
using UserService.Services;
using Xunit;

namespace UserService.Tests;

[Trait("Epic", "332")]
public class CustomerDirectoryControllerTests
{
    private static CustomerDirectoryController ControllerWith(params User[] users)
    {
        var service = new Mock<IUserService>();
        service.Setup(s => s.LookupUsersByUsernamePrefixAsync(It.IsAny<string>(), It.IsAny<int>()))
            .ReturnsAsync(users.ToList());
        var sut = new CustomerDirectoryController(service.Object, Mock.Of<ILogger<CustomerDirectoryController>>());
        sut.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext
            {
                User = new System.Security.Claims.ClaimsPrincipal(
                    new System.Security.Claims.ClaimsIdentity(new[]
                    {
                        new System.Security.Claims.Claim("userId", "banker-1")
                    }, "Test"))
            }
        };
        return sut;
    }

    [Fact]
    public void Customer_directory_lookup_is_banking_not_platform_authority()
    {
        BankingRoles.CustomerDirectoryLookup.Should().Contain("banker");
        BankingRoles.CustomerDirectoryLookup.Should().Contain("supervisor");
        BankingRoles.CustomerDirectoryLookup.Should().NotContain("admin");
    }

    [Theory]
    [InlineData("")]
    [InlineData("ab")]
    [InlineData("cas*")]
    [InlineData("cas%")]
    public async Task Lookup_rejects_short_or_wildcard_queries(string username)
    {
        var result = await ControllerWith().Lookup(username);

        result.Should().BeOfType<BadRequestObjectResult>();
    }

    [Fact]
    public async Task Lookup_returns_identity_only()
    {
        var result = await ControllerWith(new User
        {
            Id = "usr_casey",
            Username = "casey",
            Email = "casey@example.com",
            FirstName = "Casey",
            LastName = "Retail",
            IsLocked = true,
        }).Lookup("casey");

        var json = System.Text.Json.JsonSerializer.Serialize(((OkObjectResult)result).Value);
        json.Should().Contain("usr_casey");
        json.Should().Contain("casey");
        json.Should().Contain("Casey Retail");
        json.Should().Contain("locked");
        json.Should().NotContain("casey@example.com");
    }
}
