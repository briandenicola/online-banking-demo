using System.Collections.Concurrent;
using UserService.Models;

namespace UserService.Repositories;

/// <summary>
/// In-memory <see cref="ILoginAuditRepository"/> used in dev / tests.
/// </summary>
public class InMemoryLoginAuditRepository : ILoginAuditRepository
{
    private readonly ConcurrentBag<LoginAudit> _audits = new();

    public Task CreateAsync(LoginAudit audit)
    {
        _audits.Add(audit);
        return Task.CompletedTask;
    }

    public Task<List<LoginAudit>> GetRecentAsync(int limit = 100)
    {
        var audits = _audits.OrderByDescending(a => a.Timestamp).Take(limit).ToList();
        return Task.FromResult(audits);
    }
}
