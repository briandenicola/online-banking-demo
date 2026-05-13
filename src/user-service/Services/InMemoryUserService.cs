using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using UserService.Repositories;
using BC = global::BCrypt.Net.BCrypt;
using UserModel = UserService.Models.User;

namespace UserService.Services;

/// <summary>
/// In-memory variant of <see cref="UserService"/>. Same business logic as the
/// production Cosmos-backed configuration — only the storage adapters and the
/// event publisher differ.
/// </summary>
public sealed class InMemoryUserService : UserService
{
    public InMemoryUserService(ILogger<InMemoryUserService> logger, IConfiguration configuration)
        : base(
            SeedRepo(logger, configuration),
            new InMemoryLoginAuditRepository(),
            new NoOpEventPublisher(),
            NullLogger<UserService>.Instance)
    {
    }

    private static InMemoryUserRepository SeedRepo(ILogger logger, IConfiguration configuration)
    {
        var demoPassword = configuration["Demo:Password"];
        if (string.IsNullOrWhiteSpace(demoPassword))
        {
            demoPassword = Guid.NewGuid().ToString("N")[..16];
            logger.LogWarning(
                "No Demo__Password configured — generated demo password: {DemoPassword}",
                demoPassword);
        }

        var passwordHash = BC.HashPassword(demoPassword);
        var repo = new InMemoryUserRepository();

        repo.Seed(new UserModel
        {
            Id = "1",
            Username = "testuser",
            Email = "test@example.com",
            FirstName = "Test",
            LastName = "User",
            Role = Constants.Roles.Admin,
            PasswordHash = passwordHash,
            Salt = "",
        });

        repo.Seed(new UserModel
        {
            Id = "2",
            Username = "demo@banking-demo.com",
            Email = "demo@banking-demo.com",
            FirstName = "Demo",
            LastName = "User",
            Role = Constants.Roles.Admin,
            PasswordHash = passwordHash,
            Salt = "",
        });

        return repo;
    }
}
