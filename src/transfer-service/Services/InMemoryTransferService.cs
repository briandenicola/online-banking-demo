using System.Collections.Concurrent;
using OnlineBankingDemo.Contracts.Dtos;
using TransferService.Models;

namespace TransferService.Services;

public class InMemoryTransferService : ITransferService
{
    private readonly ConcurrentDictionary<string, Transfer> _transfers = new();

    public Task<Transfer> InitiateTransferAsync(string userId, CreateTransferRequest request)
    {
        var transfer = new Transfer
        {
            FromAccountNumber = request.FromAccountNumber,
            ToAccountNumber = request.ToAccountNumber,
            Amount = request.Amount,
            Description = request.Description
        };
        _transfers[transfer.Id] = transfer;
        return Task.FromResult(transfer);
    }

    public Task<Transfer?> GetTransferByIdAsync(string id)
    {
        _transfers.TryGetValue(id, out var transfer);
        return Task.FromResult(transfer);
    }
}