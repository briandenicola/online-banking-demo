using FluentAssertions;
using Microsoft.Extensions.Configuration;
using UserService.Services;
using Xunit;
using System.IdentityModel.Tokens.Jwt;

namespace UserService.Tests;

public class AuthServiceTests
{
    private readonly AuthService _sut;
    private readonly IConfiguration _configuration;

    public AuthServiceTests()
    {
        // No audience: after #334 that is retired configuration, coming from the
        // canonical registry instead. The signing key IS supplied, via the shared
        // fixture, so these tests do not silently inherit cloud-or-local mode from
        // whatever happens to be exported in the developer's shell.
        _configuration = TestJwtConfiguration.Build();

        _sut = new AuthService(_configuration);
    }

    [Fact]
    public async Task GenerateTokenAsync_ReturnsValidJwtToken()
    {
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");

        token.Should().NotBeNullOrEmpty();
        var handler = new JwtSecurityTokenHandler();
        handler.CanReadToken(token).Should().BeTrue();
    }

    [Fact]
    public async Task GenerateTokenAsync_ContainsCorrectClaims()
    {
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");

        var handler = new JwtSecurityTokenHandler();
        var jwtToken = handler.ReadJwtToken(token);

        jwtToken.Subject.Should().Be("user-123");
        jwtToken.Claims.Should().Contain(c => c.Type == "unique_name" && c.Value == "testuser");
        jwtToken.Claims.Should().Contain(c => c.Type == "userId" && c.Value == "user-123");
        jwtToken.Claims.Should().Contain(c => c.Type == JwtRegisteredClaimNames.Jti);
    }

    [Fact]
    public async Task GenerateTokenAsync_HasCorrectExpiry()
    {
        var before = DateTime.UtcNow;
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");
        var after = DateTime.UtcNow;

        var handler = new JwtSecurityTokenHandler();
        var jwtToken = handler.ReadJwtToken(token);

        jwtToken.ValidTo.Should().BeAfter(before.AddMinutes(59));
        jwtToken.ValidTo.Should().BeBefore(after.AddMinutes(61));
    }

    [Fact]
    public async Task GenerateTokenAsync_HasCorrectIssuerAndAudience()
    {
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");

        var handler = new JwtSecurityTokenHandler();
        var jwtToken = handler.ReadJwtToken(token);

        // Asserted against the canonical registry rather than restated here: a literal would
        // pass happily while the registry and the running services disagreed.
        var registry = Banking.Auth.JwtAudienceRegistry.Load(null);
        jwtToken.Issuer.Should().Be(registry.Issuer);
        jwtToken.Audiences.Should().BeEquivalentTo(registry.SessionAudiences);
        jwtToken.Audiences.Should().NotContain(registry.MediatorAudience,
            "no token a human can log in for may ever be accepted as a broker token");
    }

    [Fact]
    public async Task ValidateTokenAsync_ValidToken_ReturnsTrue()
    {
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");

        var isValid = await _sut.ValidateTokenAsync(token);

        isValid.Should().BeTrue();
    }

    [Fact]
    public async Task ValidateTokenAsync_InvalidToken_ReturnsFalse()
    {
        var isValid = await _sut.ValidateTokenAsync("invalid.token.here");

        isValid.Should().BeFalse();
    }

    [Fact]
    public async Task ValidateTokenAsync_TamperedToken_ReturnsFalse()
    {
        var token = await _sut.GenerateTokenAsync("user-123", "testuser", "user");
        var tamperedToken = token + "tampered";

        var isValid = await _sut.ValidateTokenAsync(tamperedToken);

        isValid.Should().BeFalse();
    }
}
