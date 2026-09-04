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

        // Banking authority ladder (epic #332 §5.8.3). Separation of duties
        // needs TWO DISTINCT identities to be demonstrable at all: an L2
        // approval requires a signature from the requesting banker and a
        // co-signature from someone who is not them. One account with both roles
        // would let the demo pass while proving nothing.
        //
        // Note that neither of the admins above gains banking authority — admin
        // implies neither banker nor supervisor (§5.8.2), so the ladder cannot be
        // satisfied by a single admin identity.
        var bankerEmail = configuration["Authority:BootstrapBankerEmail"];
        if (string.IsNullOrWhiteSpace(bankerEmail))
        {
            bankerEmail = "banker@banking-demo.com";
        }

        var supervisorEmail = configuration["Authority:BootstrapSupervisorEmail"];
        if (string.IsNullOrWhiteSpace(supervisorEmail))
        {
            supervisorEmail = "supervisor@banking-demo.com";
        }

        repo.Seed(new UserModel
        {
            Id = "3",
            Username = bankerEmail,
            Email = bankerEmail,
            FirstName = "Bianca",
            LastName = "Torres",
            Role = Constants.Roles.Banker,
            PasswordHash = passwordHash,
            Salt = "",
        });

        repo.Seed(new UserModel
        {
            Id = "4",
            Username = supervisorEmail,
            Email = supervisorEmail,
            FirstName = "Miriam",
            LastName = "Okafor",
            Role = Constants.Roles.Supervisor,
            PasswordHash = passwordHash,
            Salt = "",
        });

        logger.LogInformation(
            "Seeded banking authority identities: banker {BankerEmail}, supervisor {SupervisorEmail}",
            bankerEmail, supervisorEmail);

        return repo;
    }
}
