using System.IdentityModel.Tokens.Jwt;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using UserService.Services;
using Xunit;

namespace UserService.Tests;

/// <summary>
/// Guards the RATIFIED role hierarchy from epic #332 §5.8.2.
/// </summary>
/// <remarks>
/// These are not incidental unit tests. The failure mode they exist to catch is
/// a well-intentioned future edit that makes <c>admin</c> a superset "for
/// convenience" — at which point a single admin identity satisfies both
/// signatures on an L2 approval, separation of duties evaporates, and every
/// other test in the repo still passes.
/// </remarks>
public class RoleHierarchyTests
{
    private readonly IRoleHierarchy _sut = RoleHierarchy.Default;

    [Fact]
    public void Supervisor_Implies_Banker()
    {
        _sut.Expand(Constants.Roles.Supervisor)
            .Should().Contain(Constants.Roles.Banker,
                "a supervisor doing ordinary case work must not need a second account");
    }

    [Fact]
    public void Admin_Implies_Neither_Banker_Nor_Supervisor()
    {
        var expanded = _sut.Expand(Constants.Roles.Admin);

        expanded.Should().NotContain(Constants.Roles.Banker);
        expanded.Should().NotContain(Constants.Roles.Supervisor);
        expanded.Should().ContainSingle().Which.Should().Be(Constants.Roles.Admin);
    }

    [Fact]
    public void Banker_Does_Not_Imply_Supervisor()
    {
        _sut.Expand(Constants.Roles.Banker)
            .Should().NotContain(Constants.Roles.Supervisor,
                "the ladder only expands downward");
    }

    [Fact]
    public void Expansion_Always_Includes_The_Role_Itself()
    {
        foreach (var role in _sut.KnownRoles)
        {
            _sut.Expand(role).Should().Contain(role.ToLowerInvariant());
        }
    }

    [Fact]
    public void Unknown_Role_Expands_To_Itself_And_Grants_No_Seniority()
    {
        _sut.Expand("auditor").Should().ContainSingle().Which.Should().Be("auditor");
        _sut.SeniorityOf("auditor").Should().Be(0);
    }

    [Theory]
    [InlineData("user", 0)]
    [InlineData("banker", 1)]
    [InlineData("supervisor", 2)]
    // admin sits at banking seniority 0 on purpose: platform power is not
    // banking seniority, so an admin cannot fill a minSeniority >= 1 slot.
    [InlineData("admin", 0)]
    public void Seniority_Matches_The_Ratified_Ladder(string role, int expected)
    {
        _sut.SeniorityOf(role).Should().Be(expected);
    }

    [Fact]
    public void Yaml_Hierarchy_Matches_The_Builtin_Default()
    {
        // The shipped file is authoritative; the built-in default exists only as
        // a fallback. If they ever disagree, behaviour depends on whether the
        // file happened to be deployed — so assert they agree.
        var fromFile = RoleHierarchy.Load(RoleHierarchy.DefaultConfigPath);

        foreach (var role in RoleHierarchy.Default.KnownRoles)
        {
            fromFile.Expand(role).Should().BeEquivalentTo(RoleHierarchy.Default.Expand(role));
            fromFile.SeniorityOf(role).Should().Be(RoleHierarchy.Default.SeniorityOf(role));
        }
    }

    [Fact]
    public async Task Token_Carries_EffectiveRoles_And_Seniority()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Jwt:Key"] = "ThisIsATestSecretKeyThatIsAtLeast32Chars!!",
                ["Jwt:ExpiresInMinutes"] = "60",
                ["Jwt:Issuer"] = "test-issuer",
                ["Jwt:Audience"] = "test-audience"
            })
            .Build();

        var authService = new AuthService(configuration, RoleHierarchy.Default);

        var token = await authService.GenerateTokenAsync("user-9f3a", "m.okafor", Constants.Roles.Supervisor);

        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);

        var effectiveRoles = jwt.Claims
            .Where(c => c.Type == Constants.ClaimNames.EffectiveRoles)
            .Select(c => c.Value)
            .ToList();

        effectiveRoles.Should().BeEquivalentTo(new[] { Constants.Roles.Supervisor, Constants.Roles.Banker });

        jwt.Claims.Should().Contain(c =>
            c.Type == Constants.ClaimNames.Seniority && c.Value == "2");
    }

    [Fact]
    public async Task Admin_Token_Does_Not_Smuggle_In_Banking_Authority()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Jwt:Key"] = "ThisIsATestSecretKeyThatIsAtLeast32Chars!!",
                ["Jwt:ExpiresInMinutes"] = "60",
                ["Jwt:Issuer"] = "test-issuer",
                ["Jwt:Audience"] = "test-audience"
            })
            .Build();

        var authService = new AuthService(configuration, RoleHierarchy.Default);

        var token = await authService.GenerateTokenAsync("user-admin", "root", Constants.Roles.Admin);

        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(token);

        jwt.Claims.Select(c => c.Value)
            .Should().NotContain(Constants.Roles.Supervisor)
            .And.NotContain(Constants.Roles.Banker);

        jwt.Claims.Should().Contain(c =>
            c.Type == Constants.ClaimNames.Seniority && c.Value == "0");
    }
}
