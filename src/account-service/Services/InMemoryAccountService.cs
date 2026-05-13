using AccountService.Repositories;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace AccountService.Services;

/// <summary>
/// In-memory variant of <see cref="AccountService"/>. The class exists for the
/// useInMemory development mode and for tests; all business logic lives in the
/// base class — only the storage adapter (<see cref="InMemoryAccountRepository"/>)
/// differs from the production Cosmos-backed configuration.
/// </summary>
public sealed class InMemoryAccountService : AccountService
{
    public InMemoryAccountService(ILogger<InMemoryAccountService> logger)
        : base(new InMemoryAccountRepository(), NullLogger<AccountService>.Instance)
    {
        logger.LogInformation("Seeded demo accounts for users 1 and 2");
    }
}
