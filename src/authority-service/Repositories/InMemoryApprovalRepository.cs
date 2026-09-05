using AuthorityService.Models;
using Newtonsoft.Json;

namespace AuthorityService.Repositories;

/// <summary>
/// Dev/compose backend (<c>UseInMemoryDatabase=true</c>), matching the pattern the other
/// services in this repo use for local runs.
///
/// Documents are stored as serialized JSON rather than as live object references. That is
/// deliberate: it forces every read to go through the same throwing converters Cosmos would
/// use, so the closed-enum enforcement is exercised locally instead of only in Azure.
/// </summary>
public class InMemoryApprovalRepository : ApprovalRepositoryBase
{
    private readonly Dictionary<string, string> _documents = new(StringComparer.Ordinal);
    private readonly Lock _gate = new();

    public InMemoryApprovalRepository(IConfiguration configuration)
        : base(configuration.GetValue<int?>("Approval:RetentionSeconds")
               ?? throw new InvalidOperationException(
                   "Approval__RetentionSeconds is not configured. Retention is config-driven " +
                   "with no code-level default; refusing to start."))
    {
    }

    protected override Task<Approval> PersistNewAsync(Approval approval, CancellationToken ct)
    {
        lock (_gate)
        {
            if (_documents.ContainsKey(approval.Id))
            {
                throw new ApprovalWriteGuardException($"Approval {approval.Id} already exists.");
            }

            approval.ETag = Guid.NewGuid().ToString("N");
            _documents[approval.Id] = ApprovalSerialization.Serialize(approval);

            return Task.FromResult(Read(approval.Id)!);
        }
    }

    protected override Task<Approval> PersistReplaceAsync(Approval approval, CancellationToken ct)
    {
        lock (_gate)
        {
            var current = Read(approval.Id)
                          ?? throw new ApprovalWriteGuardException($"Approval {approval.Id} does not exist.");

            if (approval.ETag is not null && current.ETag is not null &&
                !string.Equals(approval.ETag, current.ETag, StringComparison.Ordinal))
            {
                throw new ApprovalConcurrencyException(approval.Id);
            }

            approval.ETag = Guid.NewGuid().ToString("N");
            _documents[approval.Id] = ApprovalSerialization.Serialize(approval);

            return Task.FromResult(Read(approval.Id)!);
        }
    }

    public override Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default)
    {
        lock (_gate)
        {
            var found = Read(id);

            return Task.FromResult(
                found is not null && string.Equals(found.RequesterId, requesterId, StringComparison.Ordinal)
                    ? found
                    : null);
        }
    }

    public override Task<Approval?> FindAsync(string id, CancellationToken ct = default)
    {
        lock (_gate)
        {
            return Task.FromResult(Read(id));
        }
    }

    public override Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default)
    {
        lock (_gate)
        {
            IEnumerable<Approval> all = ReadAll();

            if (query.Scope == ApprovalScope.AwaitingSupervisor)
            {
                var bar = query.AwaitingSeniorityAtLeast
                    ?? throw new InvalidOperationException(
                        "AwaitingSupervisor query reached the repository without a derived " +
                        "seniority bar. It is resolved from rungs.L2.cosignerRoles by " +
                        "ApprovalService; refusing to guess a literal.");

                all = all.Where(a => a.Status == ApprovalStatus.Pending && a.AwaitingSeniority >= bar);
            }

            if (query.RequesterId is not null)
                all = all.Where(a => a.RequesterId == query.RequesterId);

            if (query.ExcludeRequesterId is not null)
                all = all.Where(a => a.RequesterId != query.ExcludeRequesterId);

            if (query.SessionId is not null)
                all = all.Where(a => a.SessionId == query.SessionId);

            if (query.Status is not null)
                all = all.Where(a => a.Status == query.Status.Value);

            if (query.TerminalReason is not null)
                all = all.Where(a => a.TerminalReason == query.TerminalReason.Value);

            if (query.ActionId is not null)
                all = all.Where(a => a.ActionId == query.ActionId);

            IReadOnlyList<Approval> result = all
                .OrderByDescending(a => a.CreatedAt)
                .Take(query.Limit)
                .ToList();

            return Task.FromResult(result);
        }
    }

    public override Task<IReadOnlyList<Approval>> FindExpiredAsync(
        long nowEpochSeconds, int batchSize, CancellationToken ct = default)
    {
        lock (_gate)
        {
            IReadOnlyList<Approval> result = ReadAll()
                .Where(a => a.Status == ApprovalStatus.Pending && a.ExpiresAtEpoch <= nowEpochSeconds)
                .OrderBy(a => a.ExpiresAtEpoch)
                .Take(batchSize)
                .ToList();

            return Task.FromResult(result);
        }
    }

    public override Task<IReadOnlyList<Approval>> FindNonTerminalAsync(
        int batchSize, CancellationToken ct = default)
    {
        lock (_gate)
        {
            IReadOnlyList<Approval> result = ReadAll()
                .Where(a => !a.IsTerminal)
                .Take(batchSize)
                .ToList();

            return Task.FromResult(result);
        }
    }

    /// <summary>
    /// TEST ONLY. Writes a document while bypassing the guard, so a test can simulate
    /// store-level tampering that the service must then refuse to act on. Marked internal and
    /// exposed solely to the unit test assembly — production code has no such path.
    /// </summary>
    internal Task ForceWriteForTestAsync(Approval approval)
    {
        lock (_gate)
        {
            approval.ETag = Guid.NewGuid().ToString("N");
            _documents[approval.Id] = ApprovalSerialization.Serialize(approval);
        }

        return Task.CompletedTask;
    }

    /// <summary>
    /// TEST ONLY. The stored document exactly as written, so the schema contract test (§5.3.1b)
    /// can compare real field paths rather than a re-serialization of an in-memory object.
    /// </summary>
    internal string RawDocument(string id)
    {
        lock (_gate)
        {
            return _documents.TryGetValue(id, out var json)
                ? json
                : throw new KeyNotFoundException($"No stored document for '{id}'.");
        }
    }

    private Approval? Read(string id) =>
        _documents.TryGetValue(id, out var json)
            ? ApprovalSerialization.Deserialize<Approval>(json)
            : null;

    private IEnumerable<Approval> ReadAll() =>
        _documents.Values
            .Select(json => ApprovalSerialization.Deserialize<Approval>(json)!)
            .ToList();
}

public class ApprovalConcurrencyException : Exception
{
    public ApprovalConcurrencyException(string approvalId)
        : base($"Approval {approvalId} was modified concurrently. Retry against the current state.")
    {
        ApprovalId = approvalId;
    }

    public string ApprovalId { get; }
}
