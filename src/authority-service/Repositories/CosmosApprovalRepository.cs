using System.Net;
using AuthorityService.Models;
using Microsoft.Azure.Cosmos;

namespace AuthorityService.Repositories;

/// <summary>
/// Cosmos-backed approval store. Container <c>copilot-approvals</c>, partition key
/// <c>/requesterId</c> — the dominant read is "what is waiting for me?", which this makes a
/// single-partition query on the hottest path.
///
/// Every replace is etag-guarded, which is also what prevents a double-execute: the
/// <c>not_attempted → in_flight</c> transition is a guarded write and the executor only
/// proceeds if it wins.
/// </summary>
public class CosmosApprovalRepository : ApprovalRepositoryBase
{
    private readonly Container _container;
    private readonly ILogger<CosmosApprovalRepository> _logger;

    public CosmosApprovalRepository(
        CosmosClient client,
        IConfiguration configuration,
        ILogger<CosmosApprovalRepository> logger)
        : base(RetentionSeconds(configuration))
    {
        var database = configuration["CosmosDb:DatabaseName"] ?? "BankingDemo";
        var container = configuration["CosmosDb:ApprovalsContainerName"] ?? "copilot-approvals";

        _container = client.GetContainer(database, container);
        _logger = logger;
    }

    private static int RetentionSeconds(IConfiguration configuration) =>
        configuration.GetValue<int?>("Approval:RetentionSeconds")
        ?? throw new InvalidOperationException(
            "Approval__RetentionSeconds is not configured. Retention is config-driven with no " +
            "code-level default; refusing to start.");

    protected override async Task<Approval> PersistNewAsync(Approval approval, CancellationToken ct)
    {
        var response = await _container.CreateItemAsync(
            approval, new PartitionKey(approval.RequesterId), cancellationToken: ct);

        return response.Resource;
    }

    protected override async Task<Approval> PersistReplaceAsync(Approval approval, CancellationToken ct)
    {
        var options = new ItemRequestOptions { IfMatchEtag = approval.ETag };

        var response = await _container.ReplaceItemAsync(
            approval, approval.Id, new PartitionKey(approval.RequesterId), options, ct);

        return response.Resource;
    }

    public override async Task<Approval?> GetAsync(string id, string requesterId, CancellationToken ct = default)
    {
        try
        {
            var response = await _container.ReadItemAsync<Approval>(
                id, new PartitionKey(requesterId), cancellationToken: ct);

            return response.Resource;
        }
        catch (CosmosException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
        {
            return null;
        }
        catch (Exception ex) when (Unwrap(ex) is UnknownTerminalReasonException unknown)
        {
            // Readers fail closed: an unrecognised terminalReason means "refuses to act", never
            // "proceeds". This alerts rather than self-healing, because a silent repair would
            // erase the evidence of whatever wrote it.
            _logger.LogError(unknown,
                "ALERT: approval {ApprovalId} carries a terminalReason outside the closed enum " +
                "({Offending}). Refusing to act on it.", id, unknown.OffendingValue);

            throw unknown;
        }
    }

    public override Task<Approval?> FindAsync(string id, CancellationToken ct = default)
    {
        var query = new QueryDefinition(
                "SELECT * FROM c WHERE c.docType = 'approval' AND c.id = @id")
            .WithParameter("@id", id);

        return SingleOrDefaultAsync(query, ct);
    }

    public override async Task<IReadOnlyList<Approval>> QueryAsync(ApprovalQuery query, CancellationToken ct = default)
    {
        var sql = "SELECT * FROM c WHERE c.docType = 'approval'";
        var parameters = new Dictionary<string, object>();

        if (query.Scope == ApprovalScope.AwaitingSupervisor)
        {
            sql += " AND c.status = @pendingStatus AND c.awaitingSeniority >= @seniority";
            parameters["@pendingStatus"] = SharedIdentifiers.Status.Pending;
            parameters["@seniority"] = 2;
        }

        if (query.RequesterId is not null)
        {
            sql += " AND c.requesterId = @requesterId";
            parameters["@requesterId"] = query.RequesterId;
        }

        if (query.ExcludeRequesterId is not null)
        {
            sql += " AND c.requesterId != @excludeRequesterId";
            parameters["@excludeRequesterId"] = query.ExcludeRequesterId;
        }

        if (query.SessionId is not null)
        {
            sql += " AND c.sessionId = @sessionId";
            parameters["@sessionId"] = query.SessionId;
        }

        if (query.Status is not null)
        {
            sql += " AND c.status = @status";
            parameters["@status"] = EnumWire.ToWire(query.Status.Value);
        }

        if (query.TerminalReason is not null)
        {
            sql += " AND c.terminalReason = @terminalReason";
            parameters["@terminalReason"] = EnumWire.ToWire(query.TerminalReason.Value);
        }

        if (query.ActionId is not null)
        {
            sql += " AND c.actionId = @actionId";
            parameters["@actionId"] = query.ActionId;
        }

        sql += " ORDER BY c.createdAt DESC";

        var definition = new QueryDefinition(sql);

        foreach (var (name, value) in parameters)
        {
            definition = definition.WithParameter(name, value);
        }

        return await ReadAllAsync(definition, query.Limit, ct);
    }

    public override async Task<IReadOnlyList<Approval>> FindExpiredAsync(
        long nowEpochSeconds, int batchSize, CancellationToken ct = default)
    {
        var query = new QueryDefinition(
                "SELECT * FROM c WHERE c.docType = 'approval' AND c.status = @status " +
                "AND c.expiresAtEpoch <= @now")
            .WithParameter("@status", SharedIdentifiers.Status.Pending)
            .WithParameter("@now", nowEpochSeconds);

        return await ReadAllAsync(query, batchSize, ct);
    }

    public override async Task<IReadOnlyList<Approval>> FindNonTerminalAsync(
        int batchSize, CancellationToken ct = default)
    {
        var query = new QueryDefinition(
                "SELECT * FROM c WHERE c.docType = 'approval' AND c.status IN (@proposed, @pending, @signed)")
            .WithParameter("@proposed", SharedIdentifiers.Status.Proposed)
            .WithParameter("@pending", SharedIdentifiers.Status.Pending)
            .WithParameter("@signed", SharedIdentifiers.Status.Signed);

        return await ReadAllAsync(query, batchSize, ct);
    }

    private async Task<Approval?> SingleOrDefaultAsync(QueryDefinition query, CancellationToken ct)
    {
        var results = await ReadAllAsync(query, 1, ct);
        return results.Count > 0 ? results[0] : null;
    }

    private async Task<IReadOnlyList<Approval>> ReadAllAsync(
        QueryDefinition query, int limit, CancellationToken ct)
    {
        var results = new List<Approval>();

        using var iterator = _container.GetItemQueryIterator<Approval>(
            query, requestOptions: new QueryRequestOptions { MaxItemCount = limit });

        while (iterator.HasMoreResults && results.Count < limit)
        {
            FeedResponse<Approval> page;

            try
            {
                page = await iterator.ReadNextAsync(ct);
            }
            catch (Exception ex) when (Unwrap(ex) is UnknownTerminalReasonException unknown)
            {
                _logger.LogError(unknown,
                    "ALERT: an approval document carries a terminalReason outside the closed enum " +
                    "({Offending}). Refusing to serve this page.", unknown.OffendingValue);

                throw unknown;
            }

            results.AddRange(page);
        }

        return results.Take(limit).ToList();
    }

    private static Exception Unwrap(Exception ex)
    {
        var cursor = ex;

        while (cursor.InnerException is not null)
        {
            if (cursor is UnknownTerminalReasonException) return cursor;
            cursor = cursor.InnerException;
        }

        return cursor;
    }
}
