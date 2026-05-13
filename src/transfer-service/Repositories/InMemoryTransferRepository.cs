using System.Collections.Concurrent;
using TransferService.Models;

namespace TransferService.Repositories;

/// <summary>
/// In-memory <see cref="ITransferRepository"/> for development / test runs.
/// </summary>
public class InMemoryTransferRepository : ITransferRepository
{
    private readonly ConcurrentDictionary<string, Transfer> _transfers = new();

    public Task<Transfer?> GetByIdAsync(string id)
    {
        _transfers.TryGetValue(id, out var transfer);
        return Task.FromResult(transfer);
    }

    public Task<Transfer> CreateAsync(Transfer transfer)
    {
        _transfers[transfer.Id] = transfer;
        return Task.FromResult(transfer);
    }
}
